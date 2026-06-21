# bot/discord/bot.py
from __future__ import annotations

import asyncio
import time
from pathlib import Path
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
        self.fact_extractor = None  # set by main.py after construction
        self._start_time: float | None = None
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
        self.reaction_tracker = None  # set by main.py after construction

        # Gate V2 — optionnel, activé par response_gate.enabled dans config.
        # L'initialisation réelle est async (create_v2_tables) → faite dans setup_hook.
        self.response_gate = None   # type: ignore[assignment]
        self.cognitive_loop = None  # type: ignore[assignment]  # CognitiveLoop V2
        self.cognitive_feed = None  # type: ignore[assignment]  # CognitiveFeed (live SSE)
        self.self_fix = None        # type: ignore[assignment]  # SelfFix V2 — câblé en Plan C
        self.self_upgrade = None    # type: ignore[assignment]  # SelfUpgrade V2 — câblé en Plan C
        # Stocker le db_path pour l'init async dans setup_hook
        import os
        self._v2_db_path: str | None = (
            os.getenv("DB_PATH", "data/wally.db")
            if getattr(config, "response_gate", None) and config.response_gate.get("enabled", False)
            else None
        )

    async def setup_hook(self) -> None:
        # Gate V2 init — must be async so we can call create_v2_tables before SQLiteFactStore
        if self._v2_db_path is not None and self.response_gate is None:
            from bot.v2.db.schema_v2 import create_v2_tables
            from bot.v2.core.gate import ResponseGate
            from bot.v2.core.memory.facts import SQLiteFactStore
            from bot.core.llm.factory import create_llm_client as create_v2_llm
            from bot.config import LLMRoleConfig
            await create_v2_tables(self._v2_db_path)
            gate_llm = create_v2_llm(
                LLMRoleConfig(
                    provider="deepseek",
                    model=self.config.response_gate.get("model", "deepseek-v4-flash"),
                ),
                self.db,
            )
            self.response_gate = ResponseGate(
                llm=gate_llm,
                fact_store=SQLiteFactStore(self._v2_db_path),
                prompts_dir=Path(__file__).parent.parent / "v2" / "persona" / "prompts",
            )
            logger.info("ResponseGate V2 initialisé avec DB V2 créée ({})", self._v2_db_path)

        if getattr(self.config, "cognitive_loop", None) and self.config.cognitive_loop.get("enabled", False):
            from bot.v2.core.attention_agent import AttentionAgent
            from bot.v2.core.inner_monologue import InnerMonologue
            from bot.v2.core.meta_agent import MetaAgent
            from bot.v2.core.action_dispatcher import ActionDispatcher
            from bot.v2.core.evolution_log import EvolutionLog
            from bot.v2.core.persona_manager import PersonaManager
            from bot.v2.core.cognitive_loop import CognitiveLoop
            from bot.v2.core.cognitive_feed import CognitiveFeed
            from bot.v2.core.memory.facts import SQLiteFactStore
            from bot.core.llm.factory import create_llm_client as create_v2_llm
            from bot.config import LLMRoleConfig
            import os as _os_cog

            _db_path = self._v2_db_path or _os_cog.getenv("DB_PATH", "data/wally.db")
            _prompts_dir = Path(__file__).parent.parent / "v2" / "persona" / "prompts"
            _persona_dir = Path(__file__).parent.parent / "persona"

            _cog_cfg = self.config.cognitive_loop
            _provider = _cog_cfg.get("provider", "deepseek")
            _model_pro = _cog_cfg.get("model_pro", "deepseek-v4-pro")
            _model_flash = _cog_cfg.get("model_flash", "deepseek-v4-flash")

            _fact_store = SQLiteFactStore(_db_path)
            _mono_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)
            _meta_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_flash), self.db)
            _persona_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)

            _evo_log = EvolutionLog()
            _persona_mgr = PersonaManager(_persona_dir, _evo_log, _persona_llm, self.persona)
            _attention = AttentionAgent(_fact_store, self.emotion)
            _mono = InnerMonologue(_mono_llm, _fact_store, _prompts_dir)
            _meta = MetaAgent(_meta_llm, _prompts_dir)
            self.cognitive_feed = CognitiveFeed()
            _dispatcher = ActionDispatcher(bot=self, persona_manager=_persona_mgr, fact_store=_fact_store, feed=self.cognitive_feed)

            self.cognitive_loop = CognitiveLoop(_attention, _mono, _meta, _dispatcher, self.emotion, self.cognitive_feed)
            # setup_hook runs after AppState is built+attached in main.py, so the
            # feed must be pushed onto dashboard_state here (constructor-time getattr saw None).
            _dash = getattr(self, "dashboard_state", None)
            if _dash is not None:
                _dash.cognitive_feed = self.cognitive_feed
            logger.info("CognitiveLoop V2 initialisée ({}/{} + {})", _provider, _model_pro, _model_flash)

        import os as _os_auto
        _bridge_socket = _os_auto.getenv("BRIDGE_SOCKET_PATH", "/app/data/bridge.sock")
        _bridge_secret = _os_auto.getenv("BRIDGE_SECRET", "")
        if _bridge_socket and _bridge_secret and self.cognitive_loop is not None:
            from bot.v2.core.host_bridge import HostBridgeClient
            from bot.v2.core.self_fix import SelfFix
            from bot.v2.core.self_upgrade import SelfUpgrade
            _bridge = HostBridgeClient(_bridge_socket, _bridge_secret)
            self.self_fix = SelfFix(self.llm_secondary, _bridge, self, repo_root="/app")
            _checker = getattr(self, "update_checker", None)
            if _checker is not None:
                self.self_upgrade = SelfUpgrade(_checker, _bridge, self)
            logger.info(
                "SelfFix initialisé (bridge={}){}", _bridge_socket,
                " + SelfUpgrade" if self.self_upgrade is not None else "",
            )

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
        if self.cognitive_loop is not None:
            self.cognitive_loop.start()
        if self.self_upgrade is not None:
            self.self_upgrade.start()

    async def close(self) -> None:
        if self.self_upgrade is not None:
            await self.self_upgrade.stop()
        if self.cognitive_loop is not None:
            await self.cognitive_loop.stop()
        await super().close()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id and interaction.guild_id in self.config.discord.ignored_guilds:
            return False
        return True

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Discord error in {e}", e=event_method)
