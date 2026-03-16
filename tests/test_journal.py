# tests/test_journal.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.journal import DailyJournal


def make_deps(journal_channel_id=12345, journal_time="03:00"):
    config = MagicMock()
    config.bot.journal_channel_id = journal_channel_id
    config.bot.journal_time = journal_time

    openai = MagicMock()
    openai.complete_secondary = AsyncMock(return_value="Journal entry text.")

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )

    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[
        {"author": "Alice", "content": "Hello", "timestamp": 1000.0},
        {"author": "Wally", "content": "Hi Alice!", "timestamp": 1001.0},
    ])

    return config, openai, emotion, memory


@pytest.mark.asyncio
async def test_generate_and_send_calls_openai():
    config, openai, emotion, memory = make_deps()
    journal = DailyJournal(config, openai, emotion, memory)
    sent_messages = []
    journal.set_send_callback(AsyncMock(side_effect=lambda text: sent_messages.append(text)))

    await journal.generate_and_send()

    openai.complete_secondary.assert_called()
    assert len(sent_messages) == 1
    assert "Journal" in sent_messages[0]


@pytest.mark.asyncio
async def test_generate_skips_when_no_channel():
    config, openai, emotion, memory = make_deps(journal_channel_id=None)
    journal = DailyJournal(config, openai, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    openai.complete_secondary.assert_not_called()


@pytest.mark.asyncio
async def test_generate_skips_when_no_callback():
    config, openai, emotion, memory = make_deps()
    journal = DailyJournal(config, openai, emotion, memory)
    # No callback set — should not raise

    await journal.generate_and_send()

    openai.complete_secondary.assert_called()  # still generates, just can't send


@pytest.mark.asyncio
async def test_generate_with_empty_context():
    config, openai, emotion, memory = make_deps()
    memory.get_all_contexts = MagicMock(return_value=[])
    journal = DailyJournal(config, openai, emotion, memory)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))

    await journal.generate_and_send()

    assert len(sent) == 1  # still sends even with empty context


def test_today_format():
    journal = DailyJournal.__new__(DailyJournal)
    today = DailyJournal._today()
    assert len(today) == 10  # DD/MM/YYYY


def test_start_configures_scheduler():
    config, openai, emotion, memory = make_deps(journal_time="22:30")
    journal = DailyJournal(config, openai, emotion, memory)
    with patch("bot.core.journal.AsyncIOScheduler") as MockScheduler:
        mock_sched = MagicMock()
        MockScheduler.return_value = mock_sched
        journal.start()
        mock_sched.add_job.assert_called_once()
        call_kwargs = mock_sched.add_job.call_args
        assert call_kwargs.kwargs.get("hour") == 22
        assert call_kwargs.kwargs.get("minute") == 30
        mock_sched.start.assert_called_once()


@pytest.mark.asyncio
async def test_build_context_text_multi_pass():
    """When messages exceed token threshold, uses multi-pass summarization."""
    config, openai, emotion, memory = make_deps()
    journal = DailyJournal(config, openai, emotion, memory)

    call_count = 0

    async def fake_complete(system, messages, purpose="summary"):
        nonlocal call_count
        call_count += 1
        return f"chunk_{call_count}"

    openai.complete_secondary = fake_complete

    # 25 messages × 1000 chars = 25000 chars → 6250 tokens > 6000 threshold
    # 25 messages → 2 chunks (20 + 5) → 2 chunk summaries + 1 final = 3 calls
    big_messages = [
        {"author": "User", "content": "x" * 1000, "timestamp": float(i)}
        for i in range(25)
    ]
    result = await journal._build_context_text(big_messages)

    assert call_count == 3
    assert result == "chunk_3"  # the final combining call


# ── Arc émotionnel ────────────────────────────────────────────────────────────

def test_build_emotion_arc_returns_empty_with_less_than_2_snapshots():
    from bot.core.journal import _build_emotion_arc
    assert _build_emotion_arc([]) == ""
    assert _build_emotion_arc([{"snapshot_at": 0, "anger": 0.5, "joy": 0.0,
                                "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}]) == ""


def test_build_emotion_arc_formats_dominant_emotions():
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.75, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
        {"snapshot_at": now, "anger": 0.0, "joy": 0.55, "sadness": 0.0,
         "curiosity": 0.35, "boredom": 0.0},
    ]
    arc = _build_emotion_arc(snapshots)
    assert "Arc émotionnel" in arc
    assert "pic de joy" in arc       # 0.75 → 75% ≥ 70% → "pic de"
    assert "joy montante" in arc     # 0.55 → 55% ≥ 50% → "montante"
    assert "curiosity légère" in arc # 0.35 → 35% ≥ 30% et < 50% → "légère"
    assert arc.count("\n") >= 1


def test_build_emotion_arc_omits_emotions_below_30_percent():
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 3600, "anger": 0.1, "joy": 0.2, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
        {"snapshot_at": now, "anger": 0.1, "joy": 0.2, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},
    ]
    arc = _build_emotion_arc(snapshots)
    # Tout < 30% → chaque ligne affiche "neutre"
    assert "neutre" in arc
    assert "anger" not in arc


def test_build_emotion_arc_labels():
    """Vérifie les 3 paliers de labels."""
    from bot.core.journal import _build_emotion_arc
    import time
    now = time.time()
    snapshots = [
        {"snapshot_at": now - 7200, "anger": 0.35, "joy": 0.0, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},  # 35% → légère
        {"snapshot_at": now - 3600, "anger": 0.0, "joy": 0.6, "sadness": 0.0,
         "curiosity": 0.0, "boredom": 0.0},  # 60% → montante
        {"snapshot_at": now, "anger": 0.0, "joy": 0.0, "sadness": 0.8,
         "curiosity": 0.0, "boredom": 0.0},  # 80% → pic de
    ]
    arc = _build_emotion_arc(snapshots)
    assert "légère" in arc
    assert "montante" in arc
    assert "pic de" in arc


@pytest.mark.asyncio
async def test_journal_backward_compat_no_db():
    """DailyJournal sans db continue de fonctionner (backward compat)."""
    config, openai, emotion, memory = make_deps()
    journal = DailyJournal(config, openai, emotion, memory)  # pas de db
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_journal_emotions_text_uses_percentage():
    """Le prompt du journal contient les émotions en pourcentage."""
    config, openai, emotion, memory = make_deps()
    # joy=0.5 → 50%
    emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    assert len(captured_prompt) >= 1
    # Le dernier appel est le journal final
    final_prompt = captured_prompt[-1]
    assert "50%" in final_prompt
    assert "0.5" not in final_prompt  # pas de float brut


@pytest.mark.asyncio
async def test_journal_arc_injected_when_db_has_snapshots(tmp_path):
    """Quand la DB a ≥2 snapshots, l'arc est présent dans le prompt journal."""
    from bot.db.database import Database
    import time
    db = await Database.create(str(tmp_path / "test.db"))

    # Insérer 2 snapshots directement
    now = time.time()
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.8, 0.0, 0.0, 0.0)",
        (now - 3600,),
    )
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.5, 0.0, 0.0, 0.0)",
        (now,),
    )

    config, openai, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" in final_prompt
    await db.close()


@pytest.mark.asyncio
async def test_journal_arc_absent_when_less_than_2_snapshots(tmp_path):
    """Avec 0 ou 1 snapshot, l'arc est absent du prompt (pas de ligne vide parasite)."""
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))

    config, openai, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose=""):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    openai.complete_secondary = capture
    journal = DailyJournal(config, openai, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" not in final_prompt
    await db.close()
