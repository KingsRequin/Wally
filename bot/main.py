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

    config = Config.load(os.getenv("CONFIG_PATH", "config.yaml"))
    logger.info(
        "Config loaded — primary model: {model}, triggers: {triggers}",
        model=config.openai.primary_model,
        triggers=config.bot.trigger_names,
    )

    db_path = os.getenv("DB_PATH", "data/wally.db")
    db = await Database.create(db_path)
    logger.info("Database ready at {path}", path=db_path)

    # Core services and bot adapters will be wired here in Phase 2 and 3.
    # For now, keep the process alive to validate the skeleton.
    logger.info("Skeleton initialised — all Phase 1 services operational.")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
