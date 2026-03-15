# bot/main.py
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
    logger.add(
        "logs/wally.log",
        rotation="1 day",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
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

    # ── Core services ─────────────────────────────────────────────────────────
    emotion = EmotionEngine(config)
    emotion.start_decay_task()
    logger.info("EmotionEngine started with decay task")

    memory = MemoryService(config)
    openai_client = OpenAIClient(config, db)
    memory.set_openai_client(openai_client)
    emotion.set_openai_client(openai_client)
    logger.info("MemoryService and OpenAIClient initialized")

    prompts = PromptBuilder()
    language = LanguageDetector(config.bot.language_default)
    persona = PersonaService()
    logger.info("PromptBuilder, LanguageDetector, and PersonaService initialized")

    journal = DailyJournal(config, openai_client, emotion, memory)
    logger.info("DailyJournal initialized")

    # ── Discord adapter ───────────────────────────────────────────────────────
    from bot.discord.bot import WallyDiscord

    discord_bot = WallyDiscord(config, db, emotion, memory, openai_client, prompts, language, persona)
    discord_bot.journal = journal

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
        register_events(twitch_bot)
        tasks.append(twitch_bot.start())
        logger.info("Twitch adapter configured and included in gather")
    else:
        logger.warning(
            "Twitch bot skipped — set BOT_ACCESS_TOKEN (or BOT_REFRESH_TOKEN + "
            "TWITCH_CLIENT_ID/SECRET) to enable"
        )

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
