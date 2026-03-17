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
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

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
    await db.cleanup_old_emotion_history()
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
    emotion.set_openai_client(openai_client)
    logger.info("MemoryService and OpenAIClient initialized")

    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService()
    logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

    journal = DailyJournal(config, openai_client, emotion, memory, db=db)  # db injecté
    logger.info("DailyJournal initialized")

    from bot.core.sessions import SessionManager

    session_manager = SessionManager(memory, openai_client)
    logger.info("SessionManager initialized")

    # ── Discord adapter ───────────────────────────────────────────────────────
    from bot.discord.bot import WallyDiscord

    discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language, persona)
    discord_bot.journal = journal
    discord_bot.session_manager = session_manager

    @discord_bot.event
    async def on_message(message):
        from bot.discord.handlers import handle_message
        await handle_message(discord_bot, message)

    async def journal_send_cb(text: str) -> None:
        channel_id = config.bot.journal_channel_id
        if channel_id:
            ch = discord_bot.get_channel(channel_id)
            if ch:
                await ch.send(text)

    journal.set_send_callback(journal_send_cb)
    journal.start()
    logger.info("Discord adapter configured, journal scheduler started")

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
        twitch_bot.session_manager = session_manager
        register_events(twitch_bot)
        tasks.append(twitch_bot.start())
        logger.info("Twitch adapter configured and included in gather")
    else:
        logger.warning(
            "Twitch bot skipped — set BOT_ACCESS_TOKEN (or BOT_REFRESH_TOKEN + "
            "TWITCH_CLIENT_ID/SECRET) to enable"
        )

    # ── Dashboard ─────────────────────────────────────────────────────────────
    from bot.dashboard.app import create_dashboard_app
    from bot.dashboard.state import AppState
    import uvicorn

    _twitch_bot_ref = twitch_bot if token_manager.bot_token else None
    _twitch_api_ref = twitch_api if token_manager.bot_token else None

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
    )

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
