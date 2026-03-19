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

    def __init__(self, memory: "MemoryService", openai: "OpenAIClient", db=None) -> None:
        self._memory = memory
        self._openai = openai
        self._db = db
        self._sessions: dict[str, _Session] = {}
        # Strong refs pour éviter que le GC n'annule les tâches
        self._bg_tasks: set[asyncio.Task] = set()

    def _fire(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

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

        ts = time.time()
        session.messages.append(
            {
                "author": display_name,
                "user_id": user_id,
                "content": content,
                "timestamp": ts,
            }
        )
        session.participants[user_id] = display_name
        session.last_activity = ts

        # Persister en SQLite pour survivre aux redémarrages
        if self._db is not None:
            self._fire(self._db.insert_session_message(
                channel_id, platform, user_id, display_name, content, ts,
            ))

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
            # Nettoyer la DB même pour les sessions trop courtes
            if self._db is not None:
                await self._db.delete_session_messages(channel_id)
            return

        logger.info(
            "Session fermée — canal {ch}, {n} messages, {u} participant(s)",
            ch=channel_id,
            n=len(session.messages),
            u=len(session.participants),
        )
        task = asyncio.create_task(self._analyze_and_cleanup(session))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _analyze_and_cleanup(self, session: _Session) -> int:
        """Analyse la session puis supprime les messages persistés."""
        try:
            return await self._analyze_session(session)
        finally:
            if self._db is not None:
                try:
                    await self._db.delete_session_messages(session.channel_id)
                except Exception as e:
                    logger.warning("Failed to cleanup session_messages: {e}", e=e)

    async def _analyze_session(self, session: _Session) -> int:
        try:
            conversation = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in session.messages
            )
            analysis = await self._openai.complete_secondary(
                _ANALYSIS_SYSTEM,
                [{"role": "user", "content": conversation}],
                purpose="session_analysis",
            )
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
                    user_facts,
                    username=display_name,
                )
                stored += 1
            logger.info(
                "Analyse de session stockée pour {n}/{total} participant(s) — canal {ch}",
                n=stored,
                total=len(session.participants),
                ch=session.channel_id,
            )
            return stored
        except Exception as e:
            logger.error("Erreur lors de l'analyse de session: {e}", e=e)
            return 0

    async def restore_sessions(self) -> int:
        """Reconstruit les sessions actives depuis la DB après un redémarrage.

        Retourne le nombre de sessions restaurées.
        """
        if self._db is None:
            return 0

        since = time.time() - SESSION_TIMEOUT_SECONDS
        try:
            rows = await self._db.get_recent_session_messages(since)
        except Exception as e:
            logger.warning("Failed to restore sessions: {e}", e=e)
            return 0

        if not rows:
            return 0

        # Grouper par channel_id
        channels: dict[str, list[dict]] = {}
        for row in rows:
            channels.setdefault(row["channel_id"], []).append(row)

        restored = 0
        for channel_id, messages in channels.items():
            session = _Session(
                channel_id=channel_id,
                platform=messages[0]["platform"],
            )
            for msg in messages:
                session.messages.append({
                    "author": msg["display_name"],
                    "user_id": msg["user_id"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                })
                session.participants[msg["user_id"]] = msg["display_name"]
            session.last_activity = messages[-1]["timestamp"]

            # Calculer le délai restant avant timeout
            elapsed = time.time() - session.last_activity
            remaining = max(0.0, SESSION_TIMEOUT_SECONDS - elapsed)

            self._sessions[channel_id] = session
            task = asyncio.create_task(self._wait_and_close(channel_id, remaining))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
            session.timeout_task = task
            restored += 1

        logger.info(
            "Sessions restaurées: {n} canal/canaux, {m} messages",
            n=restored,
            m=len(rows),
        )
        return restored

    async def analyze_channel_messages(
        self,
        messages: list,  # list[discord.Message] — pas d'import discord ici
        platform: str,
        channel_id: str,
        bot_user_id: int,
    ) -> int:
        """Analyse une liste de messages Discord et stocke les faits durables en mémoire.

        Retourne le nombre de participants pour lesquels des faits ont été stockés.
        Lève ValueError si moins de 2 messages d'auteurs humains sont présents.
        """
        # 1. Filtrage
        filtered = []
        for msg in messages:
            # Exclure les bots autres que Wally
            if msg.author.bot and msg.author.id != bot_user_id:
                continue
            # Exclure les messages vides
            if not msg.content.strip():
                continue
            filtered.append(msg)

        # 2. Vérifier qu'il y a assez de messages humains
        human_count = sum(1 for m in filtered if not m.author.bot)
        if human_count < 2:
            raise ValueError(
                f"Pas assez de messages humains pour analyser : {human_count} (minimum 2)"
            )

        # 3. Conversion en dicts session
        converted = [
            {
                "author": msg.author.display_name,
                "user_id": str(msg.author.id),
                "content": msg.content,
                "timestamp": msg.created_at.timestamp(),
            }
            for msg in filtered
        ]

        # 4. Construction de la session
        participants = {
            str(msg.author.id): msg.author.display_name
            for msg in filtered
            if not msg.author.bot
        }
        session = _Session(
            channel_id=channel_id,
            platform=platform,
            messages=converted,
            participants=participants,
            last_activity=converted[-1]["timestamp"],
            timeout_task=None,
        )

        # 5. Analyse
        return await self._analyze_session(session)
