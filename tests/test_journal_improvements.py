import time
import pytest
from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    d = await Database.create(str(tmp_path / "test.db"))
    yield d
    await d.close()


# ── emotion_peaks ──

@pytest.mark.asyncio
async def test_insert_and_get_emotion_peaks(db):
    now = time.time()
    await db.insert_emotion_peak(
        timestamp=now, emotion="joy", value=0.85,
        trigger_user="Alice", trigger_message="LOL",
        channel_id="ch1", platform="discord",
    )
    peaks = await db.get_emotion_peaks_since(now - 10)
    assert len(peaks) == 1
    assert peaks[0]["emotion"] == "joy"
    assert peaks[0]["value"] == 0.85
    assert peaks[0]["trigger_user"] == "Alice"


@pytest.mark.asyncio
async def test_get_emotion_peaks_filters_by_time(db):
    old = time.time() - 100000
    await db.insert_emotion_peak(old, "anger", 0.9, "Bob", "grrr", "ch1", "discord")
    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) == 0


# ── journal_archive ──

@pytest.mark.asyncio
async def test_insert_and_get_journal(db):
    await db.insert_journal("2026-03-19", "Mon journal.", 2)
    j = await db.get_yesterday_journal("2026-03-20")
    assert j is not None
    assert j["content"] == "Mon journal."
    assert j["word_count"] == 2


@pytest.mark.asyncio
async def test_get_yesterday_journal_returns_none_when_missing(db):
    j = await db.get_yesterday_journal("2026-03-20")
    assert j is None


@pytest.mark.asyncio
async def test_insert_journal_duplicate_date_replaces(db):
    await db.insert_journal("2026-03-19", "V1", 1)
    await db.insert_journal("2026-03-19", "V2", 1)
    j = await db.get_yesterday_journal("2026-03-20")
    assert j["content"] == "V2"


# ── daily_log platform migration ──

@pytest.mark.asyncio
async def test_daily_log_has_platform_column(db):
    await db.log_daily_message("ch1", "Alice", "Hello", platform="twitch")
    rows = await db.get_today_messages()
    assert any(r.get("platform") == "twitch" for r in rows)


@pytest.mark.asyncio
async def test_daily_log_platform_defaults_to_discord(db):
    await db.log_daily_message("ch1", "Alice", "Hello")
    rows = await db.get_today_messages()
    assert rows[0].get("platform") == "discord"


# ── emotion_averages ──

@pytest.mark.asyncio
async def test_get_emotion_averages(db):
    now = time.time()
    await db.insert_emotion_snapshot({"anger": 0.2, "joy": 0.6, "sadness": 0.0, "curiosity": 0.4, "boredom": 0.1})
    await db.insert_emotion_snapshot({"anger": 0.4, "joy": 0.8, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.3})
    avgs = await db.get_emotion_averages(now - 10)
    assert avgs is not None
    assert abs(avgs["anger"] - 0.3) < 0.01
    assert abs(avgs["joy"] - 0.7) < 0.01


@pytest.mark.asyncio
async def test_get_emotion_averages_empty(db):
    avgs = await db.get_emotion_averages(time.time() - 10)
    assert avgs is None


# ── append_message platform propagation ──

import asyncio
from unittest.mock import MagicMock, AsyncMock
from bot.core.memory import MemoryService


@pytest.mark.asyncio
async def test_append_message_passes_platform_to_db():
    config = MagicMock()
    config.bot.context_window_size = 20
    memory = MemoryService(config)
    db = MagicMock()
    db.log_daily_message = AsyncMock()
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Hello", platform="twitch")

    # Let fire-and-forget task run
    await asyncio.sleep(0.05)

    db.log_daily_message.assert_called_once()
    _, kwargs = db.log_daily_message.call_args
    assert kwargs.get("platform") == "twitch" or db.log_daily_message.call_args[0][-1] == "twitch"


@pytest.mark.asyncio
async def test_append_message_platform_defaults_to_discord():
    config = MagicMock()
    config.bot.context_window_size = 20
    memory = MemoryService(config)
    db = MagicMock()
    db.log_daily_message = AsyncMock()
    memory.set_db(db)

    memory.append_message("ch1", "Alice", "Hello")

    await asyncio.sleep(0.05)

    db.log_daily_message.assert_called_once()
    # platform should default to "discord"
    call_str = str(db.log_daily_message.call_args)
    assert "discord" in call_str


# ── emotion peak detection ──

from bot.core.emotion import EmotionEngine


@pytest.mark.asyncio
async def test_process_message_logs_peak_above_threshold(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.emotions = {}
    config.bot = MagicMock()
    config.bot.emotion_peak_threshold = 0.7

    engine = EmotionEngine(config, db=db)
    # Force joy high so that any positive delta crosses threshold
    engine._state["joy"] = 0.65

    # Simulate NRCLex returning a delta that pushes joy above 0.7
    async def fake_analyze(text, trust_score=0.5):
        return {"joy": 0.1}

    engine.analyze_message = fake_analyze

    await engine.process_message("super cool gg", trust_score=0.5)

    # Wait for fire-and-forget task
    await asyncio.sleep(0.1)

    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) >= 1
    assert peaks[0]["emotion"] == "joy"
    await db.close()


@pytest.mark.asyncio
async def test_peak_antispam_prevents_duplicate(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.emotions = {}
    config.bot = MagicMock()
    config.bot.emotion_peak_threshold = 0.7

    engine = EmotionEngine(config, db=db)
    engine._state["joy"] = 0.65

    async def fake_analyze(text, trust_score=0.5):
        return {"joy": 0.1}

    engine.analyze_message = fake_analyze

    await engine.process_message("super cool gg", trust_score=0.5)
    await asyncio.sleep(0.1)

    # Second call immediately — should be blocked by anti-spam
    engine._state["joy"] = 0.65
    await engine.process_message("encore plus cool", trust_score=0.5)
    await asyncio.sleep(0.1)

    peaks = await db.get_emotion_peaks_since(time.time() - 10)
    assert len(peaks) == 1  # Only one peak, second blocked
    await db.close()


# ── stats block + word range (Task 5) ──

from bot.core.journal import _build_stats_block, _get_word_range


def test_build_stats_block_basic():
    messages = [
        {"author": "Alice", "content": "Hello", "timestamp": 1710800000.0, "platform": "discord"},
        {"author": "Bob", "content": "Hi", "timestamp": 1710803600.0, "platform": "discord"},
        {"author": "Alice", "content": "Sup", "timestamp": 1710807200.0, "platform": "twitch"},
    ]
    block = _build_stats_block(messages)
    assert "Messages : 3" in block
    assert "Participants : 2" in block
    assert "Alice (2 msgs)" in block
    assert "Discord" in block or "discord" in block


def test_build_stats_block_empty():
    block = _build_stats_block([])
    assert block == ""


def test_get_word_range():
    assert _get_word_range(10) == "150 à 250"
    assert _get_word_range(49) == "150 à 250"
    assert _get_word_range(50) == "250 à 400"
    assert _get_word_range(150) == "250 à 400"
    assert _get_word_range(151) == "400 à 600"
