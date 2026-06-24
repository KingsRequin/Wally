import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_scrape_log_and_count(tmp_path):
    db = await Database.create(str(tmp_path / "t.db"))
    assert await db.count_scrapes_today() == 0
    await db.log_scrape("https://example.com/article")
    await db.log_scrape("https://example.com/other")
    assert await db.count_scrapes_today() == 2
    await db.close()
