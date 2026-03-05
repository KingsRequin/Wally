# bot/main.py
import asyncio
from loguru import logger


async def main():
    logger.info("Wally starting...")


if __name__ == "__main__":
    asyncio.run(main())
