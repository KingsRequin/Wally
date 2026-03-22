# bot/main.py
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<level>{message}</level>"
        ),
    )

    log_dir = Path("logs") / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "app.log"),
        rotation="100 MB",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
        format="{time:HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )
    logger.add(
        str(log_dir / "error.log"),
        rotation="100 MB",
        retention="30 days",
        level="ERROR",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
    )


async def main() -> None:
    setup_logging()
    logger.info("Wally starting...")

    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.journal import DailyJournal
    from bot.core.persona import PersonaService

    # ── Load config and database ──────────────────────────────────────────────
    config = Config.load(os.getenv("CONFIG_PATH", "config.yaml"))
    logger.info(
        "Config loaded — primary model: {model}, triggers: {triggers}",
        model=config.openai.primary_model,
        triggers=config.bot.trigger_names,
    )

    db_path = os.getenv("DB_PATH", "data/wally.db")
    db = await Database.create(db_path)
    logger.info("Database ready at {path}", path=db_path)
    await db.cleanup_old_emotion_history(days=30)
    logger.info("Old emotion history cleaned up")

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    await db.sync_memory_users_from_qdrant(qdrant_url)
    logger.info("Memory users sync from Qdrant complete")

    # ── Core services ─────────────────────────────────────────────────────────
    emotion = EmotionEngine(config, db=db)          # db injecté
    await emotion.load_state()                      # charge l'état persisté
    emotion.start_decay_task()                      # APRÈS load_state
    logger.info("EmotionEngine started with decay task")

    memory = MemoryService(config)
    openai_client = OpenAIClient(config, db)
    memory.set_openai_client(openai_client)
    memory.set_db(db)
    await memory.load_aliases(db)
    emotion.set_openai_client(openai_client)
    logger.info("MemoryService and OpenAIClient initialized")

    from bot.core.web_search import WebSearchService

    web_search = WebSearchService(config, db)
    if web_search.available:
        logger.info("WebSearchService initialized (Tavily)")
    else:
        logger.warning("WebSearchService disabled — TAVILY_API_KEY missing or tavily-python not installed")

    from bot.core.apex_api import ApexLegendsService

    apex_api = ApexLegendsService()
    if apex_api.available:
        logger.info("ApexLegendsService initialized")
    else:
        logger.warning("ApexLegendsService disabled — APEX_API_KEY missing")

    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService()
    logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)  # db injecté
    logger.info("DailyJournal initialized")

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from bot.core.actions import ActionRegistry, ActionScheduler, ActionExecutor, ActionService, ActionDefinition

    # Shared scheduler
    shared_scheduler = AsyncIOScheduler()

    # Action services
    action_registry = ActionRegistry(db)
    await action_registry.load_permissions()

    action_executor = ActionExecutor(action_registry)

    from bot.dashboard.routes.sse import broadcast_action_event
    action_scheduler = ActionScheduler(db, action_executor, shared_scheduler, on_change=broadcast_action_event)

    action_service = ActionService(action_registry, action_scheduler, db)
    logger.info("ActionService initialized")

    from bot.core.fact_extractor import FactExtractor
    from bot.core.reaction_tracker import ReactionTracker

    fact_extractor = FactExtractor(config, memory, openai_client, db=db)
    await fact_extractor.restore_buffers()
    logger.info("FactExtractor initialized")

    reaction_tracker = ReactionTracker(emotion, db)
    logger.info("ReactionTracker initialized")

    # ── Discord adapter ───────────────────────────────────────────────────────
    from bot.discord.bot import WallyDiscord

    discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language, persona)
    discord_bot.journal = journal
    discord_bot.fact_extractor = fact_extractor
    discord_bot.web_search = web_search
    discord_bot.apex_api = apex_api
    discord_bot.reaction_tracker = reaction_tracker

    @discord_bot.event
    async def on_message(message):
        from bot.discord.handlers import handle_message
        await handle_message(discord_bot, message)

    async def journal_send_cb(text: str, file=None) -> None:
        channel_id = config.bot.journal_channel_id
        if channel_id:
            ch = discord_bot.get_channel(channel_id)
            if ch:
                if file and not text:
                    import discord as _discord
                    await ch.send(file=_discord.File(file, filename="emotions_jour.png"))
                elif file:
                    import discord as _discord
                    await ch.send(text, file=_discord.File(file, filename="emotions_jour.png"))
                else:
                    await ch.send(text)

    journal.set_send_callback(journal_send_cb)

    async def journal_history_cb() -> list[dict]:
        """Lit l'historique de tous les canaux Discord autorisés depuis minuit."""
        from bot.discord.handlers import _is_channel_allowed
        from datetime import datetime
        from zoneinfo import ZoneInfo
        midnight = datetime.now(ZoneInfo("Europe/Paris")).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        messages: list[dict] = []
        if not discord_bot.guilds:
            logger.warning("Journal history callback: discord_bot.guilds is empty, skipping")
            return []
        for guild in discord_bot.guilds:
            for channel in guild.text_channels:
                if not _is_channel_allowed(config, channel.id):
                    continue
                try:
                    async for msg in channel.history(after=midnight, limit=2000):
                        if not msg.content.strip():
                            continue
                        # Include all messages (humans + Wally) — journal reflects the full conversation
                        messages.append({
                            "author": msg.author.display_name,
                            "content": msg.content,
                            "timestamp": msg.created_at.timestamp(),
                        })
                except Exception as exc:
                    logger.debug(
                        "Journal history: cannot read channel {ch}: {e}",
                        ch=channel.id, e=exc,
                    )
        messages.sort(key=lambda m: m["timestamp"])
        return messages

    journal.set_history_callback(journal_history_cb)
    logger.info("Discord adapter configured")

    # ── Twitch adapter ────────────────────────────────────────────────────────
    from bot.twitch.bot import WallyTwitch
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.twitch.events import register_events

    env_path = Path(__file__).parent.parent / ".env"
    token_manager = TwitchTokenManager.load(env_path)
    await token_manager.startup_validate()

    discord_token = os.getenv("DISCORD_TOKEN", "")

    twitch_bot = None
    twitch_api = None

    tasks = [discord_bot.start(discord_token)]
    if token_manager.bot_token:
        twitch_api = TwitchAPI(
            token_manager=token_manager,
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            bot_id=os.getenv("TWITCH_BOT_ID", ""),
            broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID", ""),
        )
        twitch_bot = WallyTwitch(
            config, db, emotion, memory, openai_client, prompts, language,
            token_manager=token_manager,
            twitch_api=twitch_api,
            persona=persona,
        )
        twitch_bot.fact_extractor = fact_extractor
        twitch_bot.web_search = web_search
        twitch_bot.apex_api = apex_api
        twitch_bot.reaction_tracker = reaction_tracker
        register_events(twitch_bot)
        tasks.append(twitch_bot.start())
        logger.info("Twitch adapter configured and included in gather")
    else:
        logger.warning(
            "Twitch bot skipped — set BOT_ACCESS_TOKEN (or BOT_REFRESH_TOKEN + "
            "TWITCH_CLIENT_ID/SECRET) to enable"
        )

    # ── Action service wiring ────────────────────────────────────────────────
    discord_bot.action_service = action_service
    if twitch_bot is not None:
        twitch_bot.action_service = action_service

    # Late injection of bots into executor (twitch_bot may be None)
    action_executor.set_bots(discord_bot, twitch_bot)

    # Register built-in actions
    async def _reminder_handler(payload: dict, target: dict) -> str:
        raw_msg = payload.get("message", "Rappel!")
        creator_id = target.get("creator_id")
        platform = target.get("platform", "")

        # Build a full system prompt so the LLM speaks in Wally's voice + current mood
        try:
            system_prompt = prompts.build_system_prompt(
                emotion_state=emotion.get_state(),
                situation={"platform": platform, "datetime": True},
                persona_block=persona.build_prompt_block(),
                emotion_directives=persona.emotion_directives,
                weekday_directives=persona.weekday_directives,
                composite_directives=persona.composite_directives,
            )
            user_content = (
                f"[INSTRUCTION SYSTÈME — NE PAS CITER]\n"
                f"Tu dois envoyer un rappel à un utilisateur. "
                f"Voici le contenu du rappel : \"{raw_msg}\"\n"
                f"Formule ce rappel avec ta personnalité, ton humeur actuelle, "
                f"et ton style habituel. Sois bref (1-2 phrases max). "
                f"Ne mets PAS de mention (@), elle sera ajoutée automatiquement."
            )
            reply = await openai_client.complete_secondary(
                system_prompt,
                [{"role": "user", "content": user_content}],
                purpose="reminder",
                user_id=creator_id,
            )
            reply = reply.strip()
        except Exception as e:
            logger.warning("Reminder LLM generation failed, using raw message: {}", e)
            reply = raw_msg

        if platform == "discord" and creator_id:
            return f"<@{creator_id}> {reply}"
        return reply

    await action_registry.register("reminder", ActionDefinition(
        name="reminder",
        description="Envoyer un message de rappel",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=_reminder_handler,
    ))
    await action_registry.register("reminder_recurring", ActionDefinition(
        name="reminder_recurring",
        description="Envoyer un message de rappel récurrent",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=_reminder_handler,
    ))

    journal.start(scheduler=shared_scheduler)
    await action_scheduler.reload_all()
    shared_scheduler.start()
    logger.info("Shared scheduler started (journal + actions)")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    from bot.dashboard.app import create_dashboard_app
    from bot.dashboard.state import AppState
    import uvicorn

    _twitch_bot_ref = twitch_bot if token_manager.bot_token else None
    _twitch_api_ref = twitch_api if token_manager.bot_token else None

    from bot.core.notifications import NotificationService
    notification_service = NotificationService(config, discord_bot)

    dashboard_state = AppState(
        config=config,
        db=db,
        emotion=emotion,
        memory=memory,
        persona=persona,
        openai_client=openai_client,
        token_manager=token_manager,
        twitch_api=_twitch_api_ref,
        discord_bot=discord_bot,
        twitch_bot=_twitch_bot_ref,
        prompts=prompts,
        fact_extractor=fact_extractor,
        notifications=notification_service,
        action_service=action_service,
    )

    dashboard_state.overlay_visible = config.web_chat.overlay_visible

    discord_bot.dashboard_state = dashboard_state
    if _twitch_bot_ref is not None:
        _twitch_bot_ref.dashboard_state = dashboard_state

    dashboard_app = create_dashboard_app(dashboard_state)
    dashboard_server = uvicorn.Server(
        uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=8080,
            log_config=None,   # loguru gère les logs — désactiver uvicorn's logging
            access_log=False,
        )
    )
    tasks.append(dashboard_server.serve())
    logger.info("Dashboard server added to gather on port 8080")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
