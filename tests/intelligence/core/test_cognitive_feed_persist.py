import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.cognitive_feed import CognitiveFeed


@pytest.mark.asyncio
async def test_publish_persists_non_attn():
    store = MagicMock()
    store.append = AsyncMock()
    feed = CognitiveFeed(event_store=store)
    feed.publish({"type": "ACT", "detail": "react 🔥"})
    await asyncio.sleep(0)            # laisse la task append s'exécuter
    store.append.assert_awaited_once()
    assert store.append.await_args.args[0]["type"] == "ACT"


@pytest.mark.asyncio
async def test_publish_skips_attn_persistence():
    store = MagicMock()
    store.append = AsyncMock()
    feed = CognitiveFeed(event_store=store)
    feed.publish({"type": "ATTN", "target": "x", "content_snippet": "y"})
    await asyncio.sleep(0)
    store.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_without_store_does_not_crash():
    feed = CognitiveFeed()              # event_store=None
    feed.publish({"type": "THINK", "text": "ok"})   # ne doit pas lever
