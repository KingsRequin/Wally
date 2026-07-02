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

from bot.discord.guild_sync import parse_guild_ids  # noqa: E402  (re-exporté pour compat)


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
        intents.voice_states = True  # rejoindre/quitter salons vocaux + détecter membres en VC
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
        self.voice_service = None   # type: ignore[assignment]  # VoiceService — câblé dans setup_hook
        self.cognitive_loop = None  # type: ignore[assignment]  # CognitiveLoop V2
        self.cognitive_feed = None  # type: ignore[assignment]  # CognitiveFeed (live SSE)
        self.voice_feed = None      # type: ignore[assignment]  # VoiceFeed (live SSE debug vocal)
        self.self_fix = None        # type: ignore[assignment]  # SelfFix V2 — câblé en Plan C
        self.upgrade_registry = None  # type: ignore[assignment]  # UpgradeRegistry (Phase 6)
        self.social_rhythm = None   # type: ignore[assignment]  # SocialRhythm — câblé dans setup_hook
        self._social_rhythm_db_path: str | None = None
        # Gate de sollicitation owner partagé (self-fix + DM cognitif) : un seul
        # fil de MP vers le créateur à la fois, libéré quand il répond en DM.
        from bot.intelligence.owner_outreach import OwnerOutreachGate
        self.owner_gate = OwnerOutreachGate()
        self._wally_recent_speaks: dict[int, str] = {}  # channel_id → dernier texte envoyé
        self._catchup_done = False  # rattrapage boot lancé une seule fois par process
        self.self_upgrade = None    # type: ignore[assignment]  # SelfUpgrade V2 — câblé en Plan C
        # Stocker le db_path pour l'init async dans setup_hook
        import os
        self._v2_db_path: str | None = (
            os.getenv("DB_PATH", "data/wally.db")
            if getattr(config, "response_gate", None) and config.response_gate.get("enabled", False)
            else None
        )

    @staticmethod
    def _self_modify_allowed(bridge_socket, bridge_secret, cognitive_loop, bot_cfg) -> bool:
        """Prédicat : autorise le câblage SelfFix/SelfUpgrade uniquement si le flag
        self_modify_enabled est actif dans la config du bot ET qu'un owner est défini."""
        return bool(
            bridge_socket
            and bridge_secret
            and cognitive_loop is not None
            and getattr(bot_cfg, "self_modify_enabled", False)
            and getattr(bot_cfg, "owner_discord_id", "")
        )

    async def setup_hook(self) -> None:
        # create_v2_tables : nécessaire au gate ET aux autres composants V2.
        if self._v2_db_path is not None:
            from bot.db.schema_v2 import create_v2_tables
            await create_v2_tables(self._v2_db_path)

        # ResponseGate réactivé : avant toute réponse sur un trigger, Wally décide
        # RESPOND / IGNORE / REACT / DEFER. Mode autonome — le silence est un
        # choix légitime (cf. gate_system.md). Modèle flash, thinking off → la
        # latence reste basse (~1s).
        if (
            self._v2_db_path is not None
            and getattr(self.config, "response_gate", None)
            and self.config.response_gate.get("enabled", False)
        ):
            from bot.intelligence.gate import ResponseGate
            from bot.intelligence.memory.facts import SQLiteFactStore
            from bot.core.llm.factory import create_llm_client as _create_gate_llm
            from bot.config import LLMRoleConfig
            _gate_provider = self.config.response_gate.get("provider", "deepseek")
            _gate_model = self.config.response_gate.get("model", "deepseek-v4-flash")
            _gate_llm = _create_gate_llm(
                LLMRoleConfig(provider=_gate_provider, model=_gate_model), self.db
            )
            self.response_gate = ResponseGate(_gate_llm, SQLiteFactStore(self._v2_db_path))
            logger.info("ResponseGate réactivé ({}/{})", _gate_provider, _gate_model)

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
            # Exposé pour les routes publiques (but courant, mémoire) — #observability.
            self.fact_store = _fact_store
            # Reasoning unifié : un seul appel (pense + décide) sur le modèle "pro"
            # (celui qui portait le monologue intérieur).
            _reasoning_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)
            _persona_llm = create_v2_llm(LLMRoleConfig(provider=_provider, model=_model_pro), self.db)

            _evo_log = EvolutionLog()
            _persona_mgr = PersonaManager(_persona_dir, _evo_log, _persona_llm, self.persona)
            # Registre des demandes d'amélioration (Phase 6) : partagé entre la
            # cognition (injection « déjà demandées ») et SelfFix (écriture +
            # garde anti-redemande). Stocké pour réutilisation dans le bloc self-fix.
            from bot.intelligence.upgrade_registry import UpgradeRegistry
            self.upgrade_registry = UpgradeRegistry(_db_path)

            # Rythme social appris : réceptivité de l'audience par créneau
            # heure×semaine/weekend. Chargé depuis la DB, pré-chauffé une fois
            # depuis les logs de conversation. Aucun seuil horaire codé.
            from bot.intelligence.social_rhythm import SocialRhythm
            _tz = getattr(getattr(self.config, "circadian", None), "timezone", "Europe/Paris")
            self.social_rhythm = SocialRhythm(tz=_tz)
            self._social_rhythm_db_path = _db_path
            await self.social_rhythm.load(_db_path)
            try:
                self.social_rhythm.backfill_from_logs("logs/conversations")
            except Exception as e:  # noqa: BLE001 — le backfill ne doit jamais bloquer le boot
                logger.warning("SocialRhythm: backfill ignoré: {}", e)

            async def _latest_journal_content() -> str | None:
                # Dernier journal quotidien archivé → amorce de vagabondage (#A4).
                try:
                    entries = await self.db.get_journal_entries(limit=1)
                    return entries[0]["content"] if entries else None
                except Exception as e:  # noqa: BLE001 — jamais bloquant pour la cognition
                    logger.warning("journal_provider: lecture échouée: {}", e)
                    return None

            _attention = AttentionAgent(
                _fact_store, self.emotion,
                # (nom, code) : str(emoji) == "<:nom:id>" / "<a:nom:id>", le SEUL
                # format qu'un bot peut poster pour AFFICHER une emote custom dans
                # son texte (le raccourci ":nom:" ne marche que côté client humain).
                emote_provider=lambda: [(e.name, str(e)) for e in self.emojis],
                upgrade_registry=self.upgrade_registry,
                social_rhythm=self.social_rhythm,
                journal_provider=_latest_journal_content,
            )
            # Self-model : ce que Wally sait/ne sait pas faire (persona V1, bind-monté,
            # éditable/rechargeable). Injecté dans la cognition pour l'ancrage anti-RP
            # et le désir de capacité (DM créateur plutôt que prétendre).
            from bot.intelligence.self_model import build_self_model
            _caps_path = Path(__file__).parent.parent / "persona" / "CAPABILITIES.md"
            _caps_static = _caps_path.read_text(encoding="utf-8").strip() if _caps_path.exists() else ""
            _web_ok = bool(getattr(self, "web_search", None) and self.web_search.available)
            _caps_text = build_self_model(_caps_static, self.config, web_available=_web_ok)
            if _caps_static:
                logger.info("CAPABILITIES.md chargé pour la cognition ({} chars)", len(_caps_text))
            else:
                logger.warning("CAPABILITIES.md introuvable : {}", _caps_path)
            _reasoning = ReasoningAgent(
                _reasoning_llm, _fact_store, _prompts_dir,
                channels_text=_chan_dir.render(), capabilities_text=_caps_text,
                channel_names=_chan_dir.name_map(),
            )
            _conv_log = getattr(self, "conv_log", None)
            # Historique persistant du flux cognitif (#observability) — rotation 1000.
            from bot.intelligence.cognitive_event_store import CognitiveEventStore
            self.cognitive_event_store = CognitiveEventStore(_db_path)
            self.cognitive_feed = CognitiveFeed(
                conv_log=_conv_log, event_store=self.cognitive_event_store,
            )
            _dispatcher = ActionDispatcher(bot=self, persona_manager=_persona_mgr, fact_store=_fact_store, feed=self.cognitive_feed, twitch_bot=getattr(self, "_twitch_bot", None), gate=self.owner_gate)

            from bot.intelligence.thought_progress import ThoughtProgressJudge
            _progress_judge = ThoughtProgressJudge(self.llm_secondary, _prompts_dir)

            self.cognitive_loop = CognitiveLoop(
                _attention, _reasoning, _dispatcher, self.emotion, self.cognitive_feed,
                speakable_channels=_chan_dir.speakable_ids(),
                conv_log=_conv_log,
                fact_store=_fact_store,
                progress_judge=_progress_judge,
                social_rhythm=self.social_rhythm,
                web_search=getattr(self, "web_search", None),
                web_search_cooldown_s=self.config.tavily.cognitive_cooldown_minutes * 60,
            )
            # setup_hook runs after AppState is built+attached in main.py, so the
            # feed must be pushed onto dashboard_state here (constructor-time getattr saw None).
            _dash = getattr(self, "dashboard_state", None)
            if _dash is not None:
                _dash.cognitive_feed = self.cognitive_feed
                _dash.fact_store = self.fact_store
                _dash.cognitive_event_store = self.cognitive_event_store
            logger.info("CognitiveLoop V2 initialisée (reasoning unifié {}/{})", _provider, _model_pro)

        import os as _os_auto
        _bridge_socket = _os_auto.getenv("BRIDGE_SOCKET_PATH", "/app/data/bridge.sock")
        _bridge_secret = _os_auto.getenv("BRIDGE_SECRET", "")
        if self._self_modify_allowed(_bridge_socket, _bridge_secret, self.cognitive_loop, self.config.bot):
            from bot.intelligence.host_bridge import HostBridgeClient
            from bot.intelligence.self_fix import SelfFix
            from bot.intelligence.self_upgrade import SelfUpgrade
            _bridge = HostBridgeClient(_bridge_socket, _bridge_secret)
            # Réutilise le registre créé par le bloc cognitif ; sinon en construit
            # un (la cognition peut être désactivée mais l'auto-modif active).
            if self.upgrade_registry is None:
                from bot.intelligence.upgrade_registry import UpgradeRegistry
                _reg_db = self._v2_db_path or _os_auto.getenv("DB_PATH", "data/wally.db")
                self.upgrade_registry = UpgradeRegistry(_reg_db)
            self.self_fix = SelfFix(_bridge, self, registry=self.upgrade_registry, gate=self.owner_gate)
            _checker = getattr(self, "update_checker", None)
            if _checker is not None:
                self.self_upgrade = SelfUpgrade(_checker, _bridge, self)
            logger.info(
                "SelfFix initialisé (bridge={}){}", _bridge_socket,
                " + SelfUpgrade" if self.self_upgrade is not None else "",
            )

        self.voice_service = None
        if getattr(self.config, "voice", None) and self.config.voice.enabled:
            try:
                import os as _os_v
                from bot.discord.voice.service import VoiceService
                from bot.discord.voice.feed import VoiceFeed
                from bot.discord.voice.event_store import VoiceEventStore
                # Feed de debug vocal (live SSE + historique persistant), indépendant de la cognition.
                _voice_db = getattr(self, "_v2_db_path", None) or _os_v.getenv("DB_PATH", "data/wally.db")
                _voice_store = VoiceEventStore(_voice_db)
                self.voice_feed = VoiceFeed(event_store=_voice_store)
                _dash = getattr(self, "dashboard_state", None)
                if _dash is not None:
                    _dash.voice_feed = self.voice_feed
                    _dash.voice_event_store = _voice_store
                self.voice_service = VoiceService(self, self.config.voice)
                logger.info("VoiceService activé")
            except Exception as e:  # noqa: BLE001
                self.voice_service = None
                logger.warning("VoiceService init échouée, vocal désactivé: {e}", e=e)
        from bot.discord.commands.voice_cmd import VoiceCog
        if self.voice_service is not None:
            await self.add_cog(VoiceCog(self))

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
            for guild_id in parse_guild_ids(os.getenv("DISCORD_GUILD_ID")):
                guild = discord.Object(id=guild_id)
                self.tree.clear_commands(guild=guild)
                self.tree.copy_global_to(guild=guild)  # pousse les commandes globales sur ce guild → sync instantané
                await self.tree.sync(guild=guild)
                logger.info("Slash commands synced on guild {g}", g=guild_id)
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
        from bot.discord.channel_health import report_dead_channels
        try:
            await report_dead_channels(self)
        except Exception as e:  # noqa: BLE001
            logger.warning("channel_health au boot a échoué: {e}", e=e)

        # Auto-description des emotes custom de tous les serveurs (en tâche de
        # fond : la vision peut enchaîner des dizaines d'appels, on ne bloque
        # pas le démarrage). Idempotent : ne décrit que les emotes sans note.
        from bot.discord.emote_describer import run_emote_description
        self.loop.create_task(run_emote_description(self))

        # Rattrapage des interactions manquées pendant l'indisponibilité : scanne les
        # salons depuis le dernier log et rejoue les messages qui mentionnent Wally ou
        # répondent à l'un de ses messages. Une seule fois par process (on_ready peut
        # refirer sur reconnexion), en tâche de fond pour ne pas retarder le démarrage.
        if not self._catchup_done:
            self._catchup_done = True
            from bot.discord.catchup import run_catchup
            self.loop.create_task(run_catchup(self))

    async def on_guild_emojis_update(self, guild, before, after) -> None:
        """Décrit à chaud les nouvelles emotes ajoutées à un serveur autorisé."""
        try:
            from bot.discord.emote_describer import _guild_allowed, run_emote_description
            if _guild_allowed(self, guild) and len(after) > len(before):
                await run_emote_description(self, guild=guild)
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            logger.warning("on_guild_emojis_update a échoué: {e}", e=e)

    async def on_voice_state_update(self, member, before, after) -> None:
        """Salue les nouveaux arrivants dans le salon vocal où Wally est déjà présent."""
        vs = getattr(self, "voice_service", None)
        if vs is None or not vs.is_connected:
            return
        try:
            if member.bot or (self.user and member.id == self.user.id):
                return
            joined = after.channel is not None and after.channel.id == vs.channel_id
            was_here = before.channel is not None and before.channel.id == vs.channel_id
            if joined and not was_here:
                await vs.greet_newcomer(member)
        except Exception as e:  # noqa: BLE001
            logger.warning("on_voice_state_update a échoué: {e}", e=e)

    async def close(self) -> None:
        if self.self_upgrade is not None:
            await self.self_upgrade.stop()
        if self.cognitive_loop is not None:
            await self.cognitive_loop.stop()
        # Sauvegarde du rythme social appris (best-effort) avant l'arrêt.
        if self.social_rhythm is not None and self._social_rhythm_db_path:
            try:
                await self.social_rhythm.persist(self._social_rhythm_db_path)
            except Exception as e:  # noqa: BLE001
                logger.warning("SocialRhythm.persist au close a échoué: {}", e)
        await super().close()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id and interaction.guild_id in self.config.discord.ignored_guilds:
            return False
        return True

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Discord error in {e}", e=event_method)
