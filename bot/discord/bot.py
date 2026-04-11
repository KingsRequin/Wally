# bot/discord/bot.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from loguru import logger

from bot.discord.events import register_events

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
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
        llm: "BaseLLMClient",
        llm_secondary: "BaseLLMClient",
        image_client: "OpenAILLMClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        persona: "PersonaService",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True  # required for on_presence_update (privileged intent)
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.llm = llm
        self.llm_secondary = llm_secondary
        self.image_client = image_client
        self.prompts = prompts
        self.language = language
        self.persona = persona
        self.journal = None  # set by main.py after construction
        self.graph = None  # set by main.py after construction
        self.social = None  # SocialTracker, set by main.py after construction
        self.fact_extractor = None  # set by main.py after construction
        self._start_time: float | None = None
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
        self.reaction_tracker = None  # set by main.py after construction

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
        from bot.discord.commands.imagine import ImagineCog

        await self.add_cog(AskCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(MoodCog(self))
        await self.add_cog(MemoryCog(self))
        await self.add_cog(SetupCog(self))
        await self.add_cog(PersonaCog(self))
        await self.add_cog(JournalCog(self))
        await self.add_cog(ScanCog(self))
        await self.add_cog(TestCog(self))
        await self.add_cog(ImagineCog(self))

        register_events(self)

        # Sync slash commands — wrap in try/except so a 403 (bot not yet in guild) doesn't crash startup
        try:
            import os
            guild_id = int(os.getenv("DISCORD_GUILD_ID", "0")) or None
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            await self.tree.sync()
            logger.info("Discord slash commands synced")
        except discord.Forbidden:
            logger.warning("Discord slash commands sync skipped — bot not yet in guild (invite it first)")
        except Exception as e:
            logger.warning("Discord slash commands sync failed: {}", e)

    async def on_ready(self) -> None:
        self._start_time = time.time()
        logger.info("Discord bot ready as {user}", user=self.user)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Discord error in {e}", e=event_method)
