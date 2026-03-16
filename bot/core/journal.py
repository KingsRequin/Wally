# bot/core/journal.py
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient

_JOURNAL_SYSTEM = (
    "Tu es Wally. Écris ton journal intime de la journée. Parle de tes interactions, "
    "des personnes marquantes, de ton état émotionnel ressenti, et laisse une pensée libre. "
    "Ton ton est naturel, personnel, authentique. Ce journal est secret, juste pour toi."
)

_JOURNAL_USER_TEMPLATE = (
    "Voici un résumé de la journée :\n\n{context}\n\n"
    "Ton état émotionnel : {emotions}\n\n"
    "Écris ton journal intime pour aujourd'hui."
)

_CHUNK_SYSTEM = "Résume brièvement ces échanges en conservant les moments importants."
_FINAL_SYSTEM = "Fais une synthèse finale de ces résumés de journée."

_CHARS_PER_TOKEN = 4
_JOURNAL_TOKEN_THRESHOLD = 6000
_CHUNK_SIZE = 20
_DISCORD_LIMIT = 1900  # marge de sécurité sous la limite Discord de 2000

_TZ_JOURNAL = ZoneInfo("Europe/Paris")


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
            if pct >= 70:
                label = f"pic de {emotion} ({pct}%)"
            elif pct >= 50:
                label = f"{emotion} montante ({pct}%)"
            else:
                label = f"{emotion} légère ({pct}%)"
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
    ):
        self._config = config
        self._openai = openai
        self._emotion = emotion
        self._memory = memory
        self._send_cb: Optional[Callable[..., Any]] = None

    def set_send_callback(self, cb: Callable[..., Any]) -> None:
        """Inject an async callable: async def send(text: str) -> None"""
        self._send_cb = cb

    async def generate_and_send(self) -> None:
        channel_id = self._config.bot.journal_channel_id
        if not channel_id:
            logger.warning("No journal_channel_id configured, skipping journal")
            return

        logger.info("Generating daily journal...")

        # Gather all messages from all context windows, sorted by timestamp
        all_messages = self._memory.get_all_contexts()

        if all_messages:
            context_text = await self._build_context_text(all_messages)
        else:
            context_text = "Pas grand chose de notable aujourd'hui."

        emotions = self._emotion.get_state()
        emotions_text = ", ".join(f"{k}: {v:.2f}" for k, v in emotions.items())
        user_msg = _JOURNAL_USER_TEMPLATE.format(
            context=context_text, emotions=emotions_text
        )

        journal_text = await self._openai.complete_secondary(
            _JOURNAL_SYSTEM,
            [{"role": "user", "content": user_msg}],
            purpose="daily_journal",
        )

        formatted = f"**Journal de Wally — {self._today()}**\n\n{journal_text}"
        if self._send_cb:
            for chunk in _split_for_discord(formatted):
                await self._send_cb(chunk)
            logger.info("Daily journal sent to channel {ch}", ch=channel_id)
        else:
            logger.warning("No send callback set for journal — generated but not sent")

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
