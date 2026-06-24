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
from bot.discord.presence import PresenceService

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.intelligence.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.intelligence.persona import PersonaService


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
        intents.presences = True  # privileged — alimente le cache présence lu par PresenceService
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
        # Perception de la présence (statut + activité) des membres du serveur principal,
        # en lecture seule depuis le cache discord.py. Voir bot/discord/presence.py.
        self.presence = PresenceService(self)
        self.journal = None  # set by main.py after construction
        self.fact_extractor = None  # set by main.py after construction
        self.vision = None  # VisionService — set by main.py after construction
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
        self._wally_recent_speaks: dict[int, str] = {}  # channel_id → dernier texte envoyé
        self.self_upgrade = None    # type: ignore[assignment]  # SelfUpgrade V2 — câblé en Plan C
        # Stocker le db_path pour l'init async dans setup_hook
        import os
        self._v2_db_path: str | None = (
            os.getenv("DB_PATH", "data/wally.db")
            if getattr(config, "response_gate", None) and config.response_gate.get("enabled", False)
            else None
        )

    async def setup_hook(self) -> None:
        # Gate V2 désactivé sur les triggers — le LLM ignorait systématiquement.
        # create_v2_tables reste nécessaire pour les autres composants V2.
        if self._v2_db_path is not None:
            from bot.db.schema_v2 import create_v2_tables
            await create_v2_tables(self._v2_db_path)

        if getattr(self.config, "cognitive_loop", None) and self.config.cognitive_loop.get("enabled", False):
            from bot.intelligence.attention_agent import AttentionAgent
            from bot.intelligence.reasoning_agent import ReasoningAgent
            from bot.intelligence.action_dispatcher import ActionDispatcher
            from bot.intelligence.evolution_log import EvolutionLog
            from bot.intelligence.persona_manager import PersonaManager
            from bot.intelligence.cognitive_loop import CognitiveLoop
            from bot.intelligence.cognitive_feed import CognitiveFeed
            from bot.intelligence.channels import ChannelDirectory
            from bot.intelligence.memory.facts import SQLiteFactStore
            from bot.core.llm.factory import create_llm_client as create_v2_llm
            from bot.config import LLMRoleConfig
            import os as _os_cog

            _db_path = self._v2_db_path or _os_cog.getenv("DB_PATH", "data/wally.db")
            _v2_persona_dir = Path(__file__).parent.parent / "intelligence" / "persona"
            _prompts_dir = _v2_persona_dir / "prompts"
            _persona_dir = Path(__file__).parent.parent / "persona"

            # Annuaire des canaux (bind-mount, éditable à chaud) : permet à la
            # cognition de choisir proactivement le bon canal et élargit la
            # validation SPEAK à tout canal textuel listé.
            _chan_dir = ChannelDirectory.load(_v2_persona_dir / "CHANNELS.md")
            logger.info("ChannelDirectory : {} canal(aux) textuel(s) chargé(s)", len(_chan_dir.speakable_ids()))

            _cog_cfg = self.config.cognitive_loop
            _provider = _cog_cfg.get("provider", "deepseek")
            _model_pro = _cog_cfg.get("model_pro", "deepseek-v4-pro")

            _fact_store = SQLiteFactStore(_db_path)
            # Reasoning unifié : un seul appel (pense + décide) sur le modèle "pro"
            # (celui qui portait le monologue intérieur).
            _reasoning_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)
            _persona_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)

            _evo_log = EvolutionLog()
            _persona_mgr = PersonaManager(_persona_dir, _evo_log, _persona_llm, self.persona)
            _attention = AttentionAgent(_fact_store, self.emotion)
            # Self-model : ce que Wally sait/ne sait pas faire (persona V1, bind-monté,
            # éditable/rechargeable). Injecté dans la cognition pour l'ancrage anti-RP
            # et le désir de capacité (DM créateur plutôt que prétendre).
            _caps_path = Path(__file__).parent.parent / "persona" / "CAPABILITIES.md"
            _caps_text = _caps_path.read_text(encoding="utf-8") if _caps_path.exists() else ""
            if _caps_text:
                logger.info("CAPABILITIES.md chargé pour la cognition ({} chars)", len(_caps_text))
            else:
                logger.warning("CAPABILITIES.md introuvable : {}", _caps_path)
            _reasoning = ReasoningAgent(
                _reasoning_llm, _fact_store, _prompts_dir,
                channels_text=_chan_dir.render(), capabilities_text=_caps_text,
            )
            _conv_log = getattr(self, "conv_log", None)
            self.cognitive_feed = CognitiveFeed(conv_log=_conv_log)
            _dispatcher = ActionDispatcher(bot=self, persona_manager=_persona_mgr, fact_store=_fact_store, feed=self.cognitive_feed, twitch_bot=getattr(self, "_twitch_bot", None))

            self.cognitive_loop = CognitiveLoop(
                _attention, _reasoning, _dispatcher, self.emotion, self.cognitive_feed,
                speakable_channels=_chan_dir.speakable_ids(),
                conv_log=_conv_log,
            )
            # setup_hook runs after AppState is built+attached in main.py, so the
            # feed must be pushed onto dashboard_state here (constructor-time getattr saw None).
            _dash = getattr(self, "dashboard_state", None)
            if _dash is not None:
                _dash.cognitive_feed = self.cognitive_feed
            logger.info("CognitiveLoop V2 initialisée (reasoning unifié {}/{})", _provider, _model_pro)

        import os as _os_auto
        _bridge_socket = _os_auto.getenv("BRIDGE_SOCKET_PATH", "/app/data/bridge.sock")
        _bridge_secret = _os_auto.getenv("BRIDGE_SECRET", "")
        if _bridge_socket and _bridge_secret and self.cognitive_loop is not None:
            from bot.intelligence.host_bridge import HostBridgeClient
            from bot.intelligence.self_fix import SelfFix
            from bot.intelligence.self_upgrade import SelfUpgrade
            _bridge = HostBridgeClient(_bridge_socket, _bridge_secret)
            self.self_fix = SelfFix(_bridge, self)
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
