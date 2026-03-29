import pytest
import asyncio
import time
from bot.db.database import Database


@pytest.mark.asyncio
async def test_schema_created(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    names = {row["name"] for row in tables}
    assert {"cost_log", "timeout_log", "welcomed", "trust_scores"}.issubset(names)
    await db.close()


@pytest.mark.asyncio
async def test_log_and_get_cost(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.log_cost("gpt-4o", 100, 50, 0.001, "test")
    cost = await db.get_cost_since(time.time() - 60)
    assert cost > 0
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_default(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    score = await db.get_trust_score("discord", "unknown_user")
    assert score == 0.0  # default
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_update(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_trust_score("discord", "user1", 0.1)
    score = await db.get_trust_score("discord", "user1")
    assert abs(score - 0.1) < 0.001  # 0.0 default + 0.1 delta
    await db.close()


@pytest.mark.asyncio
async def test_trust_score_clamped(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.update_trust_score("discord", "user1", 999.0)
    score = await db.get_trust_score("discord", "user1")
    assert score == 1.0
    await db.close()


@pytest.mark.asyncio
async def test_welcomed(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert not await db.is_welcomed("user1", "guild1")
    await db.mark_welcomed("user1", "guild1")
    assert await db.is_welcomed("user1", "guild1")
    # Idempotent
    await db.mark_welcomed("user1", "guild1")
    assert await db.is_welcomed("user1", "guild1")
    await db.close()


@pytest.mark.asyncio
async def test_mute(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert not await db.is_muted("user1", "guild1")
    await db.add_timeout("user1", "guild1", duration_minutes=10, anger_level=0.9)
    assert await db.is_muted("user1", "guild1")
    await db.close()


@pytest.mark.asyncio
async def test_count_recent_triggers(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    assert await db.count_recent_triggers("user1", "guild1") == 0
    await db.add_timeout("user1", "guild1", duration_minutes=1, anger_level=0.8)
    await db.add_timeout("user1", "guild1", duration_minutes=1, anger_level=0.8)
    count = await db.count_recent_triggers("user1", "guild1", window_seconds=60)
    assert count == 2
    await db.close()


@pytest.mark.asyncio
async def test_emotion_tables_created(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    names = {row["name"] for row in tables}
    assert "emotion_state" in names
    assert "emotion_history" in names
    await db.close()


@pytest.mark.asyncio
async def test_save_and_load_emotion_state(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.3, "joy": 0.7, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1}
    await db.save_emotion_state(state)
    loaded = await db.load_emotion_state()
    for emotion, value in state.items():
        assert abs(loaded[emotion] - value) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_load_emotion_state_returns_empty_dict_when_no_data(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    loaded = await db.load_emotion_state()
    assert loaded == {}
    await db.close()


@pytest.mark.asyncio
async def test_save_emotion_state_is_idempotent(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.2, "joy": 0.6, "sadness": 0.0, "curiosity": 0.4, "boredom": 0.0}
    await db.save_emotion_state(state)
    state2 = {"anger": 0.9, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    await db.save_emotion_state(state2)
    loaded = await db.load_emotion_state()
    assert abs(loaded["anger"] - 0.9) < 0.001
    assert abs(loaded["joy"] - 0.1) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_insert_and_get_snapshots_since(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    state = {"anger": 0.2, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    await db.insert_emotion_snapshot(state)
    await db.insert_emotion_snapshot(state)
    import time
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert len(snapshots) == 2
    assert abs(snapshots[0]["joy"] - 0.5) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_get_snapshots_since_returns_empty_list_when_none(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    import time
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert snapshots == []
    await db.close()


@pytest.mark.asyncio
async def test_get_snapshots_since_excludes_old_data(tmp_path):
    """Les snapshots antérieurs au cutoff ne sont pas retournés."""
    import time
    db = await Database.create(str(tmp_path / "test.db"))
    old_ts = time.time() - 25 * 3600  # 25h avant = hors fenêtre 24h
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.1, 0.9, 0.0, 0.0, 0.0)",
        (old_ts,),
    )
    await db.insert_emotion_snapshot(
        {"anger": 0.2, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    snapshots = await db.get_emotion_snapshots_since(time.time() - 86400)
    assert len(snapshots) == 1
    assert abs(snapshots[0]["anger"] - 0.2) < 0.001
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_removes_old_snapshots(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    import time
    # Insert an 8-day-old snapshot directly via raw SQL
    old_ts = time.time() - 8 * 86400
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.0, 0.0, 0.0, 0.0)",
        (old_ts,),
    )
    # Insert a recent one
    await db.insert_emotion_snapshot(
        {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    await db.cleanup_old_emotion_history(days=7)
    rows = await db.fetch_all("SELECT * FROM emotion_history")
    assert len(rows) == 1  # seul le récent reste
    await db.close()


@pytest.mark.asyncio
async def test_daily_log_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in tables}
    assert "daily_log" in names
    await db.close()


@pytest.mark.asyncio
async def test_log_daily_message_and_get_today(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    now = time.time()
    await db.log_daily_message("ch1", "Alice", "Bonjour !", now)
    await db.log_daily_message("ch1", "Wally", "Salut Alice !", now + 1)

    msgs = await db.get_today_messages()
    assert len(msgs) == 2
    assert msgs[0]["author"] == "Alice"
    assert msgs[0]["content"] == "Bonjour !"
    assert msgs[1]["author"] == "Wally"
    await db.close()


@pytest.mark.asyncio
async def test_get_today_messages_excludes_yesterday(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    yesterday = time.time() - 86400 - 1
    today = time.time()
    await db.log_daily_message("ch1", "Alice", "Hier", yesterday)
    await db.log_daily_message("ch1", "Bob", "Aujourd'hui", today)

    msgs = await db.get_today_messages()
    assert len(msgs) == 1
    assert msgs[0]["author"] == "Bob"
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_daily_log(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    old = time.time() - 8 * 86400
    await db.log_daily_message("ch1", "Alice", "Très vieux", old)
    await db.log_daily_message("ch1", "Bob", "Récent", time.time())

    await db.cleanup_old_daily_log(days=7)
    msgs = await db.fetch_all("SELECT * FROM daily_log")
    assert len(msgs) == 1
    assert msgs[0]["author"] == "Bob"
    await db.close()


@pytest.mark.asyncio
async def test_twitch_visits_table_exists(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    tables = await db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in tables}
    assert "twitch_visits" in names
    await db.close()


@pytest.mark.asyncio
async def test_start_twitch_visit_returns_id(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    visit_id = await db.start_twitch_visit("azrael")
    assert isinstance(visit_id, int)
    assert visit_id > 0
    await db.close()


@pytest.mark.asyncio
async def test_end_twitch_visit_fills_fields(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    visit_id = await db.start_twitch_visit("azrael")
    left_at = time.time() + 600
    await db.end_twitch_visit(visit_id, left_at, 42, "Super visite chez Azrael.")
    rows = await db.fetch_all("SELECT * FROM twitch_visits WHERE id = ?", (visit_id,))
    assert len(rows) == 1
    row = rows[0]
    assert row["channel"] == "azrael"
    assert row["left_at"] == left_at
    assert row["duration_s"] == 600
    assert row["msg_count"] == 42
    assert row["summary"] == "Super visite chez Azrael."
    await db.close()


@pytest.mark.asyncio
async def test_get_twitch_visits_for_date(tmp_path):
    from datetime import date
    db = await Database.create(str(tmp_path / "test.db"))
    today = date.today().isoformat()

    # Visite aujourd'hui
    vid = await db.start_twitch_visit("streamer1")
    await db.end_twitch_visit(vid, time.time() + 100, 10, "Bonne ambiance.")

    # Visite hier (ne doit pas apparaître)
    yesterday_ts = time.time() - 86400 - 1
    await db._conn.execute(
        "INSERT INTO twitch_visits (channel, joined_at, left_at, duration_s, msg_count, summary) VALUES (?, ?, ?, ?, ?, ?)",
        ("old_channel", yesterday_ts, yesterday_ts + 300, 300, 5, "Hier."),
    )
    await db._conn.commit()

    visits = await db.get_twitch_visits_for_date(today)
    assert len(visits) == 1
    assert visits[0]["channel"] == "streamer1"
    assert visits[0]["summary"] == "Bonne ambiance."
    await db.close()
