# bot/twitch/bot.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.core.persona import PersonaService


class WallyTwitch(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        openai: "OpenAIClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        token_manager: "TwitchTokenManager",
        twitch_api: "TwitchAPI",
        persona: "PersonaService",
    ):
        super().__init__(
            token=token_manager.bot_token,
            prefix="!",
            initial_channels=[],  # No IRC connection — chat is handled via EventSub
        )
        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.openai = openai
        self.prompts = prompts
        self.language = language
        self.token_manager = token_manager
        self.twitch_api = twitch_api
        self.persona = persona
        # Per-user cooldown: {user_id: last_response_timestamp}
        self._cooldowns: dict[str, float] = {}
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]

    def is_on_cooldown(self, user_id: str) -> bool:
        last = self._cooldowns.get(user_id, 0.0)
        return (time.time() - last) < self.config.twitch.cooldown_seconds

    def set_cooldown(self, user_id: str) -> None:
        self._cooldowns[user_id] = time.time()

    async def start(self) -> None:
        """Start EventSub client — IRC connection is intentionally bypassed.

        twitchio's default start() connects to Twitch IRC (irc.chat.twitch.tv),
        which requires chat:read/chat:edit scopes. This bot uses EventSub for all
        chat traffic, so IRC is never needed and the token only carries EventSub
        scopes (user:read:chat, user:write:chat, user:bot).
        """
        logger.info("Twitch bot starting in EventSub-only mode")
        from bot.twitch.events import start_eventsub_client
        await start_eventsub_client(self)
        # Refresh tokens every 3h (Twitch user tokens expire after 4h).
        # twitchio v2 stores token strings in _Subscription objects — they cannot be
        # updated in-flight, so restarting the EventSub client is the only reliable
        # way to pick up refreshed tokens and avoid InvalidStateError on reconnect.
        try:
            while True:
                await asyncio.sleep(3 * 3600)
                logger.info("Periodic Twitch token refresh + EventSub restart")
                await self.token_manager.startup_validate()
                await self._restart_eventsub()
        except asyncio.CancelledError:
            pass

    async def _restart_eventsub(self) -> None:
        """Tear down existing EventSub sockets and reconnect with fresh tokens."""
        from bot.twitch.events import start_eventsub_client

        client = getattr(self, "_eventsub_client", None)
        if client:
            for sock in list(client._sockets):
                try:
                    if sock._pump_task and not sock._pump_task.done():
                        sock._pump_task.cancel()
                    if sock._sock and not sock._sock.closed:
                        await sock._sock.close()
                except Exception as e:
                    logger.warning("Error closing EventSub socket during restart: {e}", e=e)
            self._eventsub_client = None

        await start_eventsub_client(self)

    async def event_error(self, error: Exception, data=None) -> None:
        logger.error("Twitch error: {e}", e=error)
