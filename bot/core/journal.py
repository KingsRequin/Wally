# bot/core/journal.py
from __future__ import annotations

import time
from collections import Counter
from datetime import date, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from bot.core.emotion import EMOTIONS
from bot.core.prompts import load_prompt

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient

# Traduction des noms d'émotions internes (anglais) vers le français pour l'affichage
_EMOTION_FR = {
    "anger": "colère",
    "joy": "joie",
    "sadness": "tristesse",
    "curiosity": "curiosité",
    "boredom": "ennui",
}

_JOURNAL_SYSTEM = load_prompt(
    "journal_system",
    fallback=(
        "Tu es Wally, un bot de chat Discord. Chaque soir tu écris ton journal intime.\n\n"
        "Rédige une entrée de journal en 3 à 5 paragraphes, à la première personne, "
        "ton sincère et introspectif. Respecte la fourchette de mots indiquée dans le contexte."
    ),
)
_CHUNK_SYSTEM = load_prompt(
    "journal_chunk_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Résume le bloc de messages en 5 à 10 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
)
_FINAL_SYSTEM = load_prompt(
    "journal_final_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Synthétise les résumés en 10 à 20 lignes, "
        "texte brut, sans titre. Mentionne toujours qui a dit ou fait quoi par son pseudo exact."
    ),
)
_CHARS_PER_TOKEN = 4
_JOURNAL_TOKEN_THRESHOLD = 6000
_CHUNK_SIZE = 30
_DISCORD_LIMIT = 1900  # marge de sécurité sous la limite Discord de 2000

_TZ_JOURNAL = ZoneInfo("Europe/Paris")

_EMOTION_COLORS = {
    "anger": "#ff3333",
    "joy": "#ffdd00",
    "curiosity": "#00ccff",
    "sadness": "#7777ff",
    "boredom": "#888888",
}


def _generate_emotion_chart(snapshots: list[dict]) -> BytesIO | None:
    """Generate a dark-themed emotion chart. Returns PNG as BytesIO, or None if < 2 snapshots."""
    if len(snapshots) < 2:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    times = [datetime.fromtimestamp(s["snapshot_at"], tz=_TZ_JOURNAL) for s in snapshots]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#1a1a1a")

    for emotion in EMOTIONS:
        values = [s[emotion] * 100 for s in snapshots]
        color = _EMOTION_COLORS.get(emotion, "#ffffff")
        label = _EMOTION_FR.get(emotion, emotion).capitalize()
        ax.plot(times, values, color=color, label=label, linewidth=2)

    ax.set_ylim(0, 100)
    ax.set_ylabel("Intensité (%)", color="#aaaaaa", fontsize=10)
    ax.set_xlabel("")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh", tz=_TZ_JOURNAL))
    ax.tick_params(colors="#aaaaaa")
    ax.grid(True, color="#333333", linewidth=0.5, alpha=0.5)
    for spine in ax.spines.values():
        spine.set_color("#444444")

    ax.legend(loc="upper right", fontsize=9, facecolor="#1a1a1a", edgecolor="#444444", labelcolor="#ffffff")
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="#1a1a1a", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


def _get_word_range(message_count: int) -> str:
    """Return a word-count range string based on the number of messages."""
    if message_count < 50:
        return "150 à 250"
    if message_count <= 150:
        return "250 à 400"
    return "400 à 600"


def _build_active_hours(messages: list[dict]) -> str:
    """Build human-readable active hour ranges from messages."""
    if not messages:
        return ""
    hours: set[int] = set()
    for m in messages:
        ts = m.get("timestamp", 0)
        if ts:
            hours.add(datetime.fromtimestamp(ts, tz=_TZ_JOURNAL).hour)
    if not hours:
        return ""
    sorted_hours = sorted(hours)
    ranges: list[str] = []
    start = prev = sorted_hours[0]
    for h in sorted_hours[1:]:
        if h - prev <= 1:
            prev = h
        else:
            ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
            start = prev = h
    ranges.append(f"{start}h-{prev + 1}h" if start != prev else f"{start}h")
    return ", ".join(ranges)


def _build_stats_block(messages: list[dict]) -> str:
    """Build a stats summary block from a list of messages."""
    if not messages:
        return ""
    count = len(messages)
    authors = Counter(m["author"] for m in messages)
    unique = len(authors)
    top5 = ", ".join(f"{name} ({n} msgs)" for name, n in authors.most_common(5))
    active = _build_active_hours(messages)

    lines = [
        "Statistiques de la journée :",
        f"- Messages : {count}",
        f"- Participants : {unique}",
    ]
    if active:
        lines.append(f"- Activité : {active}")

    # Platform breakdown
    platforms = Counter(m.get("platform", "discord") for m in messages)
    if len(platforms) > 1:
        breakdown = ", ".join(f"{p.capitalize()} ({n})" for p, n in platforms.most_common())
        lines.append(f"- Plateformes : {breakdown}")

    lines.append(f"- Top participants : {top5}")
    return "\n".join(lines)


def _build_emotion_arc(snapshots: list[dict]) -> str:
    """Construit l'arc émotionnel de la journée depuis les snapshots horaires.

    Retourne "" si moins de 2 snapshots (pas assez de données pour une narrative).
    """
    if len(snapshots) < 2:
        return ""
    lines = []
    for snap in snapshots:
        ts = datetime.fromtimestamp(snap["snapshot_at"], tz=_TZ_JOURNAL)
        parts = []
        for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
            pct = int(snap[emotion] * 100)
            if pct < 30:
                continue
            name_fr = _EMOTION_FR.get(emotion, emotion)
            if pct >= 70:
                label = f"pic de {name_fr} ({pct}%)"
            elif pct >= 50:
                label = f"{name_fr} montante ({pct}%)"
            else:
                label = f"{name_fr} légère ({pct}%)"
            parts.append(label)
        if parts:
            lines.append(f"{ts.strftime('%Hh%M')} — {', '.join(parts)}")
        else:
            lines.append(f"{ts.strftime('%Hh%M')} — neutre")
    return "Arc émotionnel de la journée :\n" + "\n".join(lines)


def _split_for_discord(text: str, limit: int = _DISCORD_LIMIT) -> list[str]:
    """Découpe le texte en blocs ≤ limit caractères sur des coupures naturelles."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para) if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(para) > limit:
                # Découpe forcée si un seul paragraphe dépasse la limite
                while len(para) > limit:
                    chunks.append(para[:limit])
                    para = para[limit:]
                current = para
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


class DailyJournal:
    def __init__(
        self,
        config: "Config",
        openai: "OpenAIClient",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        db=None,
    ):
        self._config = config
        self._openai = openai
        self._emotion = emotion
        self._memory = memory
        self._db = db
        self._send_cb: Optional[Callable[..., Any]] = None
        self._fetch_history_cb: Optional[Callable[..., Any]] = None

    def set_send_callback(self, cb: Callable[..., Any]) -> None:
        """Inject an async callable: async def send(text: str) -> None"""
        self._send_cb = cb

    def set_history_callback(self, cb: Callable[..., Any]) -> None:
        """Inject an async callable: async def fetch_history() -> list[dict]
        Appelé quand daily_log est vide pour lire l'historique Discord du jour."""
        self._fetch_history_cb = cb

    async def generate_and_send(self, archive: bool = True) -> None:
        channel_id = self._config.bot.journal_channel_id
        if not channel_id:
            logger.warning("No journal_channel_id configured, skipping journal")
            return

        logger.info("Generating daily journal...")

        # Source 1 : daily_log SQLite (survit aux redémarrages, toutes plateformes)
        if self._db is not None:
            try:
                db_messages = await self._db.get_today_messages()
            except Exception as exc:
                logger.warning("Failed to get daily_log messages: {e}", e=exc)
                db_messages = []
        else:
            db_messages = []

        # Source 2 : Discord channel history (lecture API, toute la journée)
        if not db_messages and self._fetch_history_cb is not None:
            try:
                db_messages = await self._fetch_history_cb()
                if db_messages:
                    logger.info(
                        "Journal: using Discord history fallback ({n} messages)",
                        n=len(db_messages),
                    )
            except Exception as exc:
                logger.warning("Journal Discord history fallback failed: {e}", e=exc)
                db_messages = []

        # Source 3 : fenêtres RAM (depuis le dernier démarrage)
        ram_messages = self._memory.get_all_contexts()
        all_messages = db_messages if db_messages else ram_messages
        if not db_messages and ram_messages:
            logger.info("Journal: using RAM context fallback ({n} messages)", n=len(ram_messages))

        if all_messages:
            context_text = await self._build_context_text(all_messages)
        else:
            # Source 4 : souvenirs mem0 de tous les utilisateurs connus
            context_text = await self._build_mem0_fallback_context()
            if not context_text:
                logger.warning("Journal: all sources empty — generating with no conversation context")
                context_text = "Pas grand chose de notable aujourd'hui."

        # ── Stats block (F4, F8) ──
        stats_block = _build_stats_block(all_messages) if all_messages else ""

        # ── Dynamic word range (F1) ──
        word_range = _get_word_range(len(all_messages)) if all_messages else "150 à 250"

        # ── Midnight timestamp for today-based queries ──
        midnight = datetime.now(_TZ_JOURNAL).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        # ── Emotion peaks (F5) ──
        peaks_block = ""
        if self._db is not None:
            try:
                peaks = await self._db.get_emotion_peaks_since(midnight)
                if peaks:
                    peak_lines = []
                    for p in peaks:
                        ts = datetime.fromtimestamp(p["timestamp"], tz=_TZ_JOURNAL)
                        name_fr = _EMOTION_FR.get(p["emotion"], p["emotion"])
                        pct = int(p["value"] * 100)
                        user = p.get("trigger_user") or "inconnu"
                        msg = p.get("trigger_message") or ""
                        msg_short = msg[:80] + "…" if len(msg) > 80 else msg
                        peak_lines.append(
                            f"- {ts.strftime('%Hh%M')} — pic de {name_fr} ({pct}%) "
                            f"déclenché par {user} : \"{msg_short}\""
                        )
                    peaks_block = "Moments forts émotionnels :\n" + "\n".join(peak_lines)
            except Exception as exc:
                logger.warning("Failed to get emotion peaks for journal: {e}", e=exc)

        # ── Emotion arc ──
        try:
            snapshots = await self._db.get_emotion_snapshots_since(midnight) if self._db else []
        except Exception as exc:
            logger.warning("Failed to get emotion snapshots for journal: {e}", e=exc)
            snapshots = []

        arc = _build_emotion_arc(snapshots)

        # ── Comparative emotion weather (F9) ──
        weather_block = ""
        if self._db is not None:
            try:
                week_avgs = await self._db.get_emotion_averages(time.time() - 7 * 86400)
                day_avgs = await self._db.get_emotion_averages(midnight)
                if week_avgs and day_avgs:
                    diffs = []
                    for emotion in ["anger", "joy", "sadness", "curiosity", "boredom"]:
                        delta = day_avgs[emotion] - week_avgs[emotion]
                        if abs(delta) >= 0.10:
                            name_fr = _EMOTION_FR.get(emotion, emotion)
                            sign = "+" if delta > 0 else ""
                            pct = int(delta * 100)
                            direction = "plus haute que d'habitude" if delta > 0 else "en baisse"
                            diffs.append(f"{name_fr} {direction} ({sign}{pct}%)")
                    if diffs:
                        weather_block = "Comparé à la semaine : " + ", ".join(diffs)
            except Exception as exc:
                logger.warning("Failed to compute emotion weather: {e}", e=exc)

        # ── Yesterday's journal (F6) ──
        yesterday_block = ""
        if self._db is not None:
            try:
                yesterday = await self._db.get_yesterday_journal()
                if yesterday:
                    yesterday_block = f"Ton journal d'hier :\n{yesterday['content']}"
            except Exception as exc:
                logger.warning("Failed to get yesterday's journal: {e}", e=exc)

        # ── Current emotion state ──
        emotions = self._emotion.get_state()
        emotions_text = ", ".join(
            f"{_EMOTION_FR.get(k, k)}: {int(v * 100)}%" for k, v in emotions.items()
        )

        # ── Build user prompt ──
        sections = [
            f"Fourchette de mots pour cette entrée : {word_range} mots.",
        ]
        if stats_block:
            sections.append(stats_block)
        sections.append(f"Voici un résumé de la journée :\n\n{context_text}")
        if peaks_block:
            sections.append(peaks_block)
        if arc:
            sections.append(arc)
        if weather_block:
            sections.append(weather_block)
        sections.append(f"Ton état émotionnel actuel : {emotions_text}")
        if yesterday_block:
            sections.append(yesterday_block)
        sections.append("Écris ton journal intime pour aujourd'hui.")

        user_msg = "\n\n".join(sections)

        # ── Generate with primary model (F11) ──
        journal_text = await self._openai.complete(
            _JOURNAL_SYSTEM,
            [{"role": "user", "content": user_msg}],
            purpose="daily_journal",
        )

        # ── Emotion chart image (F10) ──
        chart_buf = _generate_emotion_chart(snapshots) if snapshots else None

        formatted = f"# Journal de Wally — {self._today()}\n\n{journal_text}"
        if self._send_cb:
            if chart_buf:
                await self._send_cb("", file=chart_buf)
            for chunk in _split_for_discord(formatted):
                await self._send_cb(chunk)
            logger.info("Daily journal sent to channel {ch}", ch=channel_id)
        else:
            logger.warning("No send callback set for journal — generated but not sent")

        # ── Archive (F6) ──
        if archive and self._db is not None:
            try:
                word_count = len(journal_text.split())
                await self._db.insert_journal(
                    date.today().isoformat(), journal_text, word_count,
                )
                logger.info("Journal archived ({n} words)", n=word_count)
            except Exception as exc:
                logger.warning("Failed to archive journal: {e}", e=exc)

    async def _build_context_text(self, messages: list[dict]) -> str:
        total_chars = sum(len(m["content"]) for m in messages)
        if total_chars / _CHARS_PER_TOKEN < _JOURNAL_TOKEN_THRESHOLD:
            return "\n".join(f"[{m['author']}]: {m['content']}" for m in messages)

        # Multi-pass sliding summarization
        summaries: list[str] = []
        for i in range(0, len(messages), _CHUNK_SIZE):
            chunk = messages[i : i + _CHUNK_SIZE]
            chunk_text = "\n".join(f"[{m['author']}]: {m['content']}" for m in chunk)
            s = await self._openai.complete_secondary(
                _CHUNK_SYSTEM,
                [{"role": "user", "content": chunk_text}],
                purpose="journal_chunk_summary",
            )
            summaries.append(s)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._openai.complete_secondary(
            _FINAL_SYSTEM,
            [{"role": "user", "content": combined}],
            purpose="journal_final_summary",
        )

    async def _build_mem0_fallback_context(self) -> str:
        """Fallback final : souvenirs mem0 de tous les utilisateurs connus."""
        if self._db is None:
            return ""
        try:
            users = await self._db.list_memory_users()
        except Exception as exc:
            logger.warning("Failed to list memory users for journal fallback: {e}", e=exc)
            return ""

        if not users:
            return ""

        parts: list[str] = []
        for user in users:
            uid_full = user["user_id"]   # e.g. "discord:123456"
            platform = user["platform"]
            username = user.get("username") or uid_full
            raw_id = uid_full[len(platform) + 1:]  # "discord:123" → "123"
            try:
                facts = await self._memory.get_all(platform, raw_id)
            except Exception as exc:
                logger.debug("Journal mem0 fallback: failed for user {u}: {e}", u=username, e=exc)
                continue
            if facts:
                parts.append(f"[{username}] {facts}")

        if not parts:
            return ""

        logger.info("Journal fallback: using mem0 facts for {n} user(s)", n=len(parts))
        return "Souvenirs des utilisateurs (mémoire long-terme) :\n" + "\n".join(parts)

    @staticmethod
    def _today() -> str:
        return date.today().strftime("%d/%m/%Y")

    def start(self) -> None:
        self._scheduler = AsyncIOScheduler()
        raw = self._config.bot.journal_time
        # YAML parse `21:00` sans guillemets en int sexagésimal (1260) — on normalise
        if isinstance(raw, int):
            hour, minute = divmod(raw, 60)
            time_str = f"{hour:02d}:{minute:02d}"
        else:
            time_str = str(raw)
            hour, minute = map(int, time_str.split(":"))
        self._scheduler.add_job(
            self.generate_and_send,
            "cron",
            hour=hour,
            minute=minute,
        )
        self._scheduler.start()
        logger.info("Daily journal scheduler started, fires at {t}", t=time_str)
