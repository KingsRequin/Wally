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
    try:
        feed.publish({"type": "THINK", "text": "ok"})
    except Exception as exc:            # noqa: BLE001 — le test échoue si ça lève
        pytest.fail(f"publish a levé sans event_store: {exc}")
    # l'event reste tout de même bufferisé pour le live SSE
    assert feed.snapshot()[-1]["text"] == "ok"
