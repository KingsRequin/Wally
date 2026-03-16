# bot/core/sessions.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from loguru import logger

from bot.core.prompts import load_prompt

if TYPE_CHECKING:
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient

SESSION_TIMEOUT_SECONDS = 20 * 60  # 20 minutes d'inactivité

_ANALYSIS_SYSTEM = load_prompt(
    "session_analysis_system",
    fallback=(
        "Tu es le module d'analyse de sessions de Wally. Pour chaque participant humain "
        "(exclure Wally), extrait les faits durables. Format : ### pseudo\\n- fait\\n..."
    ),
)


def _extract_user_section(analysis: str, display_name: str) -> str:
    """Extrait la section ### display_name de l'analyse LLM.

    Retourne une chaîne vide si l'utilisateur n'a pas de section.
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in analysis.split("\n"):
        if line.startswith("### "):
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = line[4:].strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections.get(display_name, "")


@dataclass
class _Session:
    channel_id: str
    platform: str
    messages: list[dict] = field(default_factory=list)
    # user_id → display_name pour chaque participant humain
    participants: dict[str, str] = field(default_factory=dict)
    last_activity: float = field(default_factory=time.time)
    timeout_task: Optional[asyncio.Task] = field(default=None, repr=False)


class SessionManager:
    """Gère les sessions de conversation par canal.

    Une session commence au premier message dans un canal et se termine
    après SESSION_TIMEOUT_SECONDS d'inactivité. À la clôture, la
    conversation est analysée de façon asynchrone et les résultats
    stockés dans la mémoire long-terme de chaque participant.
    """

    def __init__(self, memory: "MemoryService", openai: "OpenAIClient") -> None:
        self._memory = memory
        self._openai = openai
        self._sessions: dict[str, _Session] = {}
        # Strong refs pour éviter que le GC n'annule les tâches
        self._bg_tasks: set[asyncio.Task] = set()

    def record_message(
        self,
        channel_id: str,
        platform: str,
        user_id: str,
        display_name: str,
        content: str,
    ) -> None:
        """Enregistre un message dans la session active du canal."""
        session = self._sessions.get(channel_id)
        if session is None:
            session = _Session(channel_id=channel_id, platform=platform)
            self._sessions[channel_id] = session
            logger.debug("Session ouverte — canal {ch}", ch=channel_id)

        session.messages.append(
            {
                "author": display_name,
                "user_id": user_id,
                "content": content,
                "timestamp": time.time(),
            }
        )
        session.participants[user_id] = display_name
        session.last_activity = time.time()

        # Réinitialiser le timer d'inactivité
        if session.timeout_task and not session.timeout_task.done():
            session.timeout_task.cancel()

        task = asyncio.create_task(
            self._wait_and_close(channel_id, SESSION_TIMEOUT_SECONDS)
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        session.timeout_task = task

    async def _wait_and_close(self, channel_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        session = self._sessions.pop(channel_id, None)
        if session is None or len(session.messages) < 2:
            return

        logger.info(
            "Session fermée — canal {ch}, {n} messages, {u} participant(s)",
            ch=channel_id,
            n=len(session.messages),
            u=len(session.participants),
        )
        task = asyncio.create_task(self._analyze_session(session))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _analyze_session(self, session: _Session) -> None:
        try:
            conversation = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in session.messages
            )
            analysis = await self._openai.complete_secondary(
                _ANALYSIS_SYSTEM,
                [{"role": "user", "content": conversation}],
                purpose="session_analysis",
            )
            date_str = time.strftime("%d/%m/%Y")
            stored = 0
            for user_id, display_name in session.participants.items():
                user_facts = _extract_user_section(analysis, display_name)
                if not user_facts:
                    logger.debug(
                        "No durable facts for {u} in session — skipping memory",
                        u=display_name,
                    )
                    continue
                await self._memory.add(
                    session.platform,
                    user_id,
                    f"Session du {date_str}: {user_facts}",
                )
                stored += 1
            logger.info(
                "Analyse de session stockée pour {n}/{total} participant(s) — canal {ch}",
                n=stored,
                total=len(session.participants),
                ch=session.channel_id,
            )
        except Exception as e:
            logger.error("Erreur lors de l'analyse de session: {e}", e=e)
