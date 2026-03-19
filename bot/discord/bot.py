# bot/discord/bot.py
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.persona import PersonaService


class WallyDiscord(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        openai: "OpenAIClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        persona: "PersonaService",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.openai = openai
        self.prompts = prompts
        self.language = language
        self.persona = persona
        self.journal = None  # set by main.py after construction
        self.session_manager = None  # set by main.py after construction
        self._start_time: float | None = None
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]

    async def setup_hook(self) -> None:
        from bot.discord.commands.ask import AskCog
        from bot.discord.commands.status import StatusCog
        from bot.discord.commands.mood import MoodCog
        from bot.discord.commands.memory_cmd import MemoryCog
        from bot.discord.commands.setup import SetupCog
        from bot.discord.commands.persona_cmd import PersonaCog
        from bot.discord.commands.journal_cmd import JournalCog
        from bot.discord.commands.scan_cmd import ScanCog
        from bot.discord.commands.test_cmd import TestCog

        await self.add_cog(AskCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(MoodCog(self))
        await self.add_cog(MemoryCog(self))
        await self.add_cog(SetupCog(self))
        await self.add_cog(PersonaCog(self))
        await self.add_cog(JournalCog(self))
        await self.add_cog(ScanCog(self))
        await self.add_cog(TestCog(self))
        await self.tree.sync()
        logger.info("Discord slash commands synced")

    async def on_ready(self) -> None:
        self._start_time = time.time()
        logger.info("Discord bot ready as {user}", user=self.user)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Discord error in {e}", e=event_method)
