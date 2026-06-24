# tests/test_auto_scrape.py
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

import bot.discord.handlers as H


def _msg(content, channel_id="chan1"):
    m = MagicMock()
    m.content = content
    m.channel.id = channel_id
    return m


def _bot(cooldown=30, enabled=True, scrape_return="Contenu page."):
    b = MagicMock()
    b.config.firecrawl.auto_scrape_links = enabled
    b.config.firecrawl.auto_scrape_cooldown_s = cooldown
    b.scrape.available = True
    b.scrape.is_scrapable_url = lambda u: u.startswith("http") and not u.endswith(".png")
    b.scrape.scrape = AsyncMock(return_value=scrape_return)
    return b


@pytest.mark.asyncio
async def test_auto_scrape_extracts_first_link():
    H._scrape_cooldowns.clear()
    bot = _bot()
    out = await H._auto_scrape_block(bot, _msg("regarde ça https://example.com/a et ça https://example.com/b"))
    assert "Contenu page." in out
    bot.scrape.scrape.assert_awaited_once_with("https://example.com/a")


@pytest.mark.asyncio
async def test_auto_scrape_ignores_media_link():
    H._scrape_cooldowns.clear()
    bot = _bot()
    out = await H._auto_scrape_block(bot, _msg("photo https://example.com/x.png"))
    assert out == ""
    bot.scrape.scrape.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_scrape_respects_cooldown():
    H._scrape_cooldowns.clear()
    bot = _bot(cooldown=999)
    await H._auto_scrape_block(bot, _msg("https://example.com/a"))
    out = await H._auto_scrape_block(bot, _msg("https://example.com/c"))
    assert out == ""  # cooldown actif


@pytest.mark.asyncio
async def test_auto_scrape_disabled():
    H._scrape_cooldowns.clear()
    bot = _bot(enabled=False)
    out = await H._auto_scrape_block(bot, _msg("https://example.com/a"))
    assert out == ""
