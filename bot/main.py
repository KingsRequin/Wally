# bot/main.py
import asyncio
import os
import sys

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
    logger.info("MemoryService and OpenAIClient initialized")

    prompts = PromptBuilder(config.bot.system_prompt)
    language = LanguageDetector(config.bot.language_default)
    logger.info("PromptBuilder and LanguageDetector initialized")

    journal = DailyJournal(config, openai_client, emotion, memory)
    logger.info("DailyJournal initialized")

    logger.info("All Phase 2 core services operational — ready for Discord/Twitch adapters")

    # Discord and Twitch bots wired in Phase 3 and 4.
    # asyncio.gather(discord_bot.start(), twitch_bot.start()) goes here.

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
