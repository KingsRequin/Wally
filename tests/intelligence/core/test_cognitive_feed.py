import asyncio
import pytest
from bot.intelligence.cognitive_feed import CognitiveFeed


def test_publish_appends_to_snapshot_buffer():
    feed = CognitiveFeed(buffer_size=3)
    feed.publish({"type": "THINK", "text": "a"})
    feed.publish({"type": "SPEAK", "detail": "b"})
    snap = feed.snapshot()
    assert [e["type"] for e in snap] == ["THINK", "SPEAK"]
    assert snap[0]["text"] == "a"


def test_buffer_is_circular():
    feed = CognitiveFeed(buffer_size=2)
    for i in range(5):
        feed.publish({"type": "THINK", "n": i})
    snap = feed.snapshot()
    assert [e["n"] for e in snap] == [3, 4]


@pytest.mark.asyncio
async def test_subscribe_receives_published_events():
    feed = CognitiveFeed()
    q = feed.subscribe()
    feed.publish({"type": "ACT", "detail": "x"})
    evt = await asyncio.wait_for(q.get(), timeout=1)
    assert evt["type"] == "ACT"
    feed.unsubscribe(q)
    assert q not in feed._queues


def test_publish_swallows_full_queue():
    feed = CognitiveFeed()
    feed.subscribe()
    for i in range(feed._queue_maxsize + 5):
        feed.publish({"type": "THINK", "n": i})
    assert True  # no exception
