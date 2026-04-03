#!/usr/bin/env python3
"""
Script one-shot : importe les entrées de journal depuis le canal Discord configuré.

Usage (depuis la racine du projet) :
    python scripts/import_journal_from_discord.py [--limit 200]

Le script lit config.yaml pour trouver journal_channel_id et DATABASE_PATH,
se connecte à Discord, lit l'historique du canal, et insère les entrées
manquantes dans journal_archive.

À exécuter une seule fois pour récupérer les anciens journaux.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

# Ajoute la racine du projet au sys.path
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
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_journal_date(header_line: str) -> str | None:
    m = _ISO_RE.search(header_line)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_RE.search(header_line)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = MONTH_FR.get(month_str)
        if month:
            return f"{year}-{month:02d}-{day:02d}"
    return None


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
            print(f"❌ Canal {channel_id} introuvable — vérifie que le bot est dans le serveur")
            await client.close()
            return

        print(f"→ Lecture de {limit} messages depuis #{channel.name}…")
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async for msg in channel.history(limit=limit, oldest_first=False):
                content = msg.content.strip()
                if not content.startswith("# Journal de Wally"):
                    continue
                first_line = content.split("\n", 1)[0]
                date_str = _parse_journal_date(first_line)
                if not date_str:
                    skipped += 1
                    print(f"  ⚠ Impossible de parser la date : {first_line!r}")
                    continue
                body = content.split("\n", 1)[1].strip() if "\n" in content else content
                word_count = len(body.split())
                await db.execute(
                    "INSERT INTO journal_archive (date, content, word_count, created_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(date) DO UPDATE SET content=excluded.content, "
                    "word_count=excluded.word_count, created_at=excluded.created_at",
                    (date_str, body, word_count, time.time()),
                )
                imported += 1
                print(f"  ✓ {date_str}  ({word_count} mots)")
            await db.commit()

        print(f"\nImport terminé : {imported} entrées importées, {skipped} ignorées.")
        await client.close()

    import os
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        print("❌ DISCORD_TOKEN introuvable dans .env")
        sys.exit(1)

    await client.start(token)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Import journal Discord → SQLite")
    parser.add_argument("--limit", type=int, default=200, help="Nombre de messages à lire (défaut: 200)")
    args = parser.parse_args()
    asyncio.run(run(args.limit))
