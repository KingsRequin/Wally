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
        # Keep the task alive — EventSub runs its own async tasks.
        try:
            await asyncio.sleep(float("inf"))
        except asyncio.CancelledError:
            pass

    async def event_error(self, error: Exception, data=None) -> None:
        logger.error("Twitch error: {e}", e=error)
