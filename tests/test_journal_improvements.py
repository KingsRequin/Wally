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
from bot.intelligence.memory.service import MemoryService


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
    config.bot.emotion_inertia_factor = 0.5

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
    config.bot.emotion_inertia_factor = 0.5

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

from bot.intelligence.journal import _build_stats_block, _get_length_guidance


def test_build_stats_block_basic():
    messages = [
        {"author": "Alice", "content": "Hello", "timestamp": 1710800000.0, "platform": "discord"},
        {"author": "Bob", "content": "Hi", "timestamp": 1710803600.0, "platform": "discord"},
        {"author": "Alice", "content": "Sup", "timestamp": 1710807200.0, "platform": "twitch"},
    ]
    block = _build_stats_block(messages)
    # Aucun compteur : un chiffre injecté finit récité tel quel dans l'entrée publiée
    assert "Messages :" not in block
    assert "Participants :" not in block
    assert "msgs" not in block
    # Mais on garde qui était là, dans l'ordre de bavardage, et quand
    assert block.index("Alice") < block.index("Bob")
    assert "Moments d'activité" in block
    assert "Discord" in block or "discord" in block


def test_build_stats_block_empty():
    block = _build_stats_block([])
    assert block == ""


def test_length_guidance_is_a_ceiling_never_a_floor():
    """Un plancher de mots force le remplissage, et le remplissage produit de la broderie."""
    for count in (0, 9, 10, 49, 50, 150, 151, 5000):
        guidance = _get_length_guidance(count)
        assert "maximum" in guidance
        assert "minimum" not in guidance

    # Journée quasi muette → on autorise explicitement l'entrée expédiée
    creuse = _get_length_guidance(1)
    assert "80 mots maximum" in creuse
    assert "n'invente pas" in creuse

    assert "200 mots maximum" in _get_length_guidance(49)
    assert "400 mots maximum" in _get_length_guidance(150)
    assert "600 mots maximum" in _get_length_guidance(151)


# ── Task 6: Wire everything into generate_and_send ──

@pytest.mark.asyncio
async def test_journal_injects_stats_and_length_guidance(tmp_path):
    """Stats block, word range, and peaks are injected in the journal prompt."""
    from unittest.mock import MagicMock, AsyncMock
    from bot.intelligence.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    now = time.time()
    # Insert messages into daily_log
    for i in range(60):
        await db_inst.log_daily_message("ch1", "Alice" if i % 2 == 0 else "Bob", f"msg {i}", platform="discord")
    # Insert a peak
    await db_inst.insert_emotion_peak(now, "joy", 0.85, "Alice", "LOL", "ch1", "discord")
    # Insert yesterday's journal
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await db_inst.insert_journal(yesterday, "Journal d'hier : tout était calme.", 6)

    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7

    openai_mock = MagicMock()
    openai_mock.complete = AsyncMock(return_value="Summary text.")

    captured_journal_prompt = []
    async def fake_complete(system, messages, purpose="", **kwargs):
        captured_journal_prompt.append(messages[0]["content"])
        return "Generated journal text"

    openai_mock.complete = fake_complete

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[])

    journal = DailyJournal(config, openai_mock, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    assert len(captured_journal_prompt) >= 1
    # First call is always the main journal prompt (voice pass is a subsequent call)
    prompt = captured_journal_prompt[0]
    assert "Qui était là" in prompt
    assert "400 mots maximum" in prompt
    await db_inst.close()


@pytest.mark.asyncio
async def test_journal_archives_after_send(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from bot.intelligence.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7
    openai_mock = MagicMock()
    openai_mock.complete = AsyncMock(return_value="Summary.")
    openai_mock.complete = AsyncMock(return_value="Mon journal du jour.")
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[{"author": "A", "content": "hi", "timestamp": 1000.0}])

    journal = DailyJournal(config, openai_mock, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    # La date de PARIS, pas celle de l'horloge machine : le serveur tourne en
    # UTC, et entre 22 h UTC et minuit `date.today()` rend encore la veille
    # alors que la journée parisienne — celle que le journal archive — a déjà
    # changé. Ces tests échouaient donc deux heures par nuit.
    today = DailyJournal._today_date().isoformat()
    row = await db_inst.fetch_one("SELECT * FROM journal_archive WHERE date = ?", (today,))
    assert row is not None
    assert "Mon journal du jour." in row["content"]
    await db_inst.close()


@pytest.mark.asyncio
async def test_journal_archive_false_does_not_archive(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from bot.intelligence.journal import DailyJournal

    db_inst = await Database.create(str(tmp_path / "test.db"))
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7
    openai_mock = MagicMock()
    openai_mock.complete = AsyncMock(return_value="Summary.")
    openai_mock.complete = AsyncMock(return_value="Test journal.")
    emotion = MagicMock()
    emotion.get_state = MagicMock(return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0})
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[{"author": "A", "content": "hi", "timestamp": 1000.0}])

    journal = DailyJournal(config, openai_mock, openai_mock, emotion, memory, db=db_inst)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send(archive=False)

    # La date de PARIS, pas celle de l'horloge machine : le serveur tourne en
    # UTC, et entre 22 h UTC et minuit `date.today()` rend encore la veille
    # alors que la journée parisienne — celle que le journal archive — a déjà
    # changé. Ces tests échouaient donc deux heures par nuit.
    today = DailyJournal._today_date().isoformat()
    row = await db_inst.fetch_one("SELECT * FROM journal_archive WHERE date = ?", (today,))
    assert row is None
    await db_inst.close()


# ── Task 7: Emotion chart (F10) ──

from bot.intelligence.journal import _generate_emotion_chart


def test_generate_emotion_chart_returns_bytes():
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 7200, "anger": 0.1, "joy": 0.6, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0},
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.5, "boredom": 0.1},
        {"snapshot_at": now, "anger": 0.2, "joy": 0.5, "sadness": 0.1, "curiosity": 0.4, "boredom": 0.0},
    ]
    buf = _generate_emotion_chart(snapshots)
    assert buf is not None
    data = buf.getvalue()
    assert len(data) > 1000  # should be a valid PNG
    assert data[:4] == b'\x89PNG'


def test_generate_emotion_chart_returns_none_with_less_than_2():
    assert _generate_emotion_chart([]) is None
    assert _generate_emotion_chart([{"snapshot_at": 0, "anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}]) is None


# ── Task 8: /wally test command (F12) ──

@pytest.mark.asyncio
async def test_test_command_cog_exists():
    from bot.discord.commands.test_cmd import TestCog
    assert TestCog is not None


# ── Task 9: get_journals_last_n_days ──

@pytest.mark.asyncio
async def test_get_journals_last_n_days_basic(db):
    await db.insert_journal("2026-04-10", "Jour 10", 2)
    await db.insert_journal("2026-04-11", "Jour 11", 2)
    await db.insert_journal("2026-04-12", "Jour 12", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert len(result) == 3
    assert result[0]["date"] == "2026-04-10"
    assert result[2]["date"] == "2026-04-12"
    assert result[0]["content"] == "Jour 10"


@pytest.mark.asyncio
async def test_get_journals_last_n_days_excludes_before_date(db):
    await db.insert_journal("2026-04-12", "Hier", 2)
    await db.insert_journal("2026-04-13", "Aujourd'hui", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert len(result) == 1
    assert result[0]["date"] == "2026-04-12"


@pytest.mark.asyncio
async def test_get_journals_last_n_days_respects_n(db):
    for i in range(1, 8):
        await db.insert_journal(f"2026-04-0{i}", f"Jour {i}", 2)
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-08")
    assert len(result) == 4
    assert result[0]["date"] == "2026-04-04"


@pytest.mark.asyncio
async def test_get_journals_last_n_days_empty(db):
    result = await db.get_journals_last_n_days(n=4, before_date="2026-04-13")
    assert result == []


# ── Continuité : habitués sans nouvelles ──

@pytest.mark.asyncio
async def test_missing_regulars_detects_absent_habitue(db):
    now = time.time()
    await db.execute(
        "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
        "VALUES (?,?,?,?,?)",
        ("discord:1", "discord", now - 40 * 86400, "Keychka", 25),
    )
    missing = await db.get_missing_regulars(now=now)
    assert [m["username"] for m in missing] == ["Keychka"]
    assert missing[0]["days"] == 40


@pytest.mark.asyncio
async def test_missing_regulars_ignores_someone_who_just_spoke(db):
    """Un souvenir ne se forme pas à chaque message : last_updated peut vieillir à tort."""
    now = time.time()
    await db.execute(
        "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
        "VALUES (?,?,?,?,?)",
        ("discord:2", "discord", now - 40 * 86400, "Iron d'aile", 16),
    )
    await db.log_daily_message("ch1", "Iron d'aile (@iron_daile)", "je suis là", platform="discord")
    assert await db.get_missing_regulars(now=now) == []


@pytest.mark.asyncio
async def test_missing_regulars_ignores_occasional_visitors(db):
    now = time.time()
    await db.execute(
        "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
        "VALUES (?,?,?,?,?)",
        ("twitch:3", "twitch", now - 60 * 86400, "passant", 2),
    )
    assert await db.get_missing_regulars(now=now) == []


@pytest.mark.asyncio
async def test_missing_regulars_ranks_by_closeness(db):
    now = time.time()
    for uid, name, count, days in (
        ("discord:4", "Proche", 25, 20),
        ("discord:5", "Lointain", 9, 90),
    ):
        await db.execute(
            "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
            "VALUES (?,?,?,?,?)",
            (uid, "discord", now - days * 86400, name, count),
        )
    # Trié par nombre de souvenirs, pas par fraîcheur de l'absence
    assert [m["username"] for m in await db.get_missing_regulars(now=now)] == ["Proche", "Lointain"]


@pytest.mark.asyncio
async def test_missing_regulars_survit_a_une_date_illisible(db):
    """Une ligne corrompue ne doit pas faire disparaître tout le bloc des absents.

    SQLite a une affinité faible : un texte passe dans une colonne REAL NOT NULL,
    et float() lève alors ValueError.
    """
    now = time.time()
    await db.execute(
        "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
        "VALUES (?,?,?,?,?)",
        ("discord:90", "discord", "pas-une-date", "Cassé", 20),
    )
    await db.execute(
        "INSERT INTO memory_users (user_id, platform, last_updated, username, memory_count) "
        "VALUES (?,?,?,?,?)",
        ("discord:91", "discord", now - 30 * 86400, "Valide", 15),
    )
    missing = await db.get_missing_regulars(now=now)
    assert [m["username"] for m in missing] == ["Valide"]
