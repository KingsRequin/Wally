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
