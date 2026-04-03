#!/usr/bin/env python3
"""
Script one-shot : importe les entrées de journal depuis le canal Discord configuré.

Usage (depuis la racine du projet) :
    python3 scripts/import_journal_from_discord.py [--limit 500]

Gère les journaux découpés en plusieurs messages consécutifs (limite 2000 chars Discord).
Les messages consécutifs du bot envoyés dans la même fenêtre de 10 minutes sont fusionnés.

À exécuter une seule fois pour récupérer les anciens journaux.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiosqlite
import discord
from dotenv import load_dotenv
from bot.config import Config

MONTH_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}
_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})", re.IGNORECASE)
_ISO_RE  = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_SLASH_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

# Messages du même journal envoyés à moins de 10 minutes d'intervalle sont fusionnés
MAX_GAP_SECONDS = 600


def _parse_journal_date(header_line: str) -> str | None:
    m = _ISO_RE.search(header_line)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _SLASH_RE.search(header_line)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year}-{month:02d}-{day:02d}"
    m = _DATE_RE.search(header_line)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = MONTH_FR.get(month_str)
        if month:
            return f"{year}-{month:02d}-{day:02d}"
    return None


@dataclass
class JournalEntry:
    date_str: str
    parts: list[str] = field(default_factory=list)
    last_ts: float = 0.0
    chart_path: str | None = None  # local path after download

    def full_content(self) -> str:
        return "\n\n".join(p.strip() for p in self.parts if p.strip())

    def word_count(self) -> int:
        return len(self.full_content().split())


async def run(limit: int) -> None:
    config = Config.load()
    channel_id = config.bot.journal_channel_id
    if not channel_id:
        print("❌ journal_channel_id non configuré dans config.yaml")
        sys.exit(1)

    db_path = Path("data/wally.db")
    if not db_path.exists():
        print(f"❌ Base de données introuvable : {db_path}")
        sys.exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    imported = 0
    skipped = 0

    @client.event
    async def on_ready() -> None:
        nonlocal imported, skipped
        print(f"✓ Connecté en tant que {client.user}")
        channel = client.get_channel(int(channel_id))
        if channel is None:
            print(f"❌ Canal {channel_id} introuvable")
            await client.close()
            return

        print(f"→ Lecture de {limit} messages depuis #{channel.name} (oldest_first)…")

        # Collect all bot messages oldest→newest (text + image attachments)
        bot_id = client.user.id
        raw_messages: list[discord.Message] = []
        async for msg in channel.history(limit=limit, oldest_first=True):
            if msg.author.id == bot_id:
                if msg.content.strip() or msg.attachments:
                    raw_messages.append(msg)

        print(f"  {len(raw_messages)} messages du bot trouvés")

        # Group into journal entries:
        # A new entry starts when a message begins with "# Journal de Wally"
        # Subsequent messages from the bot within MAX_GAP_SECONDS are appended to it
        entries: list[JournalEntry] = []
        current: JournalEntry | None = None

        for msg in raw_messages:
            content = msg.content.strip()
            ts = msg.created_at.replace(tzinfo=timezone.utc).timestamp()

            if content.startswith("# Journal de Wally"):
                # New journal entry
                first_line = content.split("\n", 1)[0]
                date_str = _parse_journal_date(first_line)
                if not date_str:
                    print(f"  ⚠ Date non parsable : {first_line!r}")
                    skipped += 1
                    current = None
                    continue
                body = content.split("\n", 1)[1].strip() if "\n" in content else ""
                current = JournalEntry(date_str=date_str, parts=[body] if body else [], last_ts=ts)
                entries.append(current)

            elif current is not None and ts - current.last_ts <= MAX_GAP_SECONDS:
                # Emotion chart: "# Historique de mes émotions" + attachment — download via Discord
                if content.startswith("# Historique") and msg.attachments:
                    img_att = next(
                        (a for a in msg.attachments if not a.content_type or 'image' in a.content_type),
                        msg.attachments[0] if msg.attachments else None,
                    )
                    if img_att and current.chart_path is None:
                        charts_dir = Path("data/journal_charts")
                        charts_dir.mkdir(parents=True, exist_ok=True)
                        chart_file = charts_dir / f"{current.date_str}.png"
                        if not chart_file.exists():
                            print(f"    → téléchargement chart {current.date_str}…")
                            try:
                                await img_att.save(chart_file)
                                print(f"    ✓ chart OK ({chart_file.stat().st_size // 1024} Ko)")
                            except Exception as e:
                                print(f"    ⚠ chart : {e}")
                                chart_file = None
                        if chart_file and chart_file.exists():
                            current.chart_path = str(chart_file)
                    current.last_ts = ts
                elif content:
                    current.parts.append(content)
                    current.last_ts = ts
            else:
                current = None

        print(f"  {len(entries)} entrées de journal détectées\n")

        async with aiosqlite.connect(db_path) as db:
            for entry in entries:
                full = entry.full_content()
                wc = entry.word_count()
                await db.execute(
                    "INSERT INTO journal_archive (date, content, word_count, created_at, chart_path) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(date) DO UPDATE SET content=excluded.content, "
                    "word_count=excluded.word_count, created_at=excluded.created_at, "
                    "chart_path=COALESCE(excluded.chart_path, chart_path)",
                    (entry.date_str, full, wc, time.time(), entry.chart_path),
                )
                imported += 1
                chart_info = " + chart" if entry.chart_path else ""
                print(f"  ✓ {entry.date_str}  ({wc} mots, {len(entry.parts)} partie(s)){chart_info}")
            await db.commit()

        print(f"\nImport terminé : {imported} entrées importées, {skipped} ignorées.")
        await client.close()

    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        print("❌ DISCORD_TOKEN introuvable dans .env")
        sys.exit(1)

    await client.start(token)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Import journal Discord → SQLite")
    parser.add_argument("--limit", type=int, default=500, help="Nombre de messages à lire (défaut: 500)")
    args = parser.parse_args()
    asyncio.run(run(args.limit))
