"""Tests VoiceEventStore (persistance + rotation) et VoiceFeed (live fan-out)."""
import asyncio
import os
import tempfile

import aiosqlite
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.discord.voice.event_store import VoiceEventStore
from bot.discord.voice.feed import VoiceFeed


_DDL = """
CREATE TABLE IF NOT EXISTS voice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL
);
"""


@pytest.fixture
async def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    async with aiosqlite.connect(path) as db:
        await db.executescript(_DDL)
        await db.commit()
    yield path
    os.unlink(path)


# ---------------------------------------------------------------- VoiceEventStore

async def test_store_append_then_recent_roundtrip(db_path):
    store = VoiceEventStore(db_path)
    await store.append({"type": "heard", "speaker": "Alex", "text": "salut wally"})
    rows = await store.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["type"] == "heard"
    assert rows[0]["speaker"] == "Alex"
    assert rows[0]["text"] == "salut wally"
    assert "id" in rows[0] and "ts" in rows[0]


async def test_store_rotation_garde_les_n_derniers(db_path):
    store = VoiceEventStore(db_path, cap=3)
    for i in range(6):
        await store.append({"type": "heard", "text": f"msg{i}"})
    rows = await store.recent(limit=50)
    assert len(rows) == 3
    assert [r["text"] for r in rows] == ["msg5", "msg4", "msg3"]  # ordre décroissant


async def test_store_recent_pagination_before_id(db_path):
    store = VoiceEventStore(db_path)
    for i in range(5):
        await store.append({"type": "heard", "text": f"m{i}"})
    page1 = await store.recent(limit=2)
    assert [r["text"] for r in page1] == ["m4", "m3"]
    page2 = await store.recent(limit=2, before_id=page1[-1]["id"])
    assert [r["text"] for r in page2] == ["m2", "m1"]


# ---------------------------------------------------------------- VoiceFeed

async def test_feed_publish_bufferise_et_persiste():
    store = MagicMock()
    store.append = AsyncMock()
    feed = VoiceFeed(event_store=store)
    feed.publish({"type": "reply", "text": "coucou"})
    await asyncio.sleep(0)
    store.append.assert_awaited_once()
    assert feed.snapshot()[-1]["text"] == "coucou"


async def test_feed_sans_store_ne_crash_pas():
    feed = VoiceFeed()
    feed.publish({"type": "heard", "text": "ok"})
    assert feed.snapshot()[-1]["text"] == "ok"


async def test_feed_subscriber_recoit_les_events():
    feed = VoiceFeed()
    q = feed.subscribe()
    feed.publish({"type": "heard", "text": "hello"})
    evt = await asyncio.wait_for(q.get(), timeout=1.0)
    assert evt["text"] == "hello"
    feed.unsubscribe(q)
