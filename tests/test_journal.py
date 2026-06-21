# tests/test_journal.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.intelligence.journal import DailyJournal


def make_deps(journal_channel_id=12345, journal_time="03:00"):
    config = MagicMock()
    config.bot.journal_channel_id = journal_channel_id
    config.bot.journal_time = journal_time
    config.bot.emotion_peak_threshold = 0.7

    llm = MagicMock()
    llm.complete = AsyncMock(return_value="Journal entry text.")

    llm_secondary = MagicMock()
    llm_secondary.complete = AsyncMock(return_value="Journal entry text.")

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )

    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[
        {"author": "Alice", "content": "Hello", "timestamp": 1000.0},
        {"author": "Wally", "content": "Hi Alice!", "timestamp": 1001.0},
    ])

    return config, llm, llm_secondary, emotion, memory


@pytest.mark.asyncio
async def test_generate_and_send_calls_llm():
    config, llm, llm_secondary, emotion, memory = make_deps()
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    sent_messages = []
    journal.set_send_callback(AsyncMock(side_effect=lambda text, **kw: sent_messages.append(text)))

    await journal.generate_and_send()

    llm.complete.assert_called()
    assert len(sent_messages) == 1
    assert "Journal" in sent_messages[0]


@pytest.mark.asyncio
async def test_generate_skips_when_no_channel():
    config, llm, llm_secondary, emotion, memory = make_deps(journal_channel_id=None)
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    llm.complete.assert_not_called()
    llm_secondary.complete.assert_not_called()


@pytest.mark.asyncio
async def test_generate_skips_when_no_callback():
    config, llm, llm_secondary, emotion, memory = make_deps()
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    # No callback set — should not raise

    await journal.generate_and_send()

    llm.complete.assert_called()  # still generates, just can't send


@pytest.mark.asyncio
async def test_generate_with_empty_context():
    config, llm, llm_secondary, emotion, memory = make_deps()
    memory.get_all_contexts = MagicMock(return_value=[])
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))

    await journal.generate_and_send()

    assert len(sent) == 1  # still sends even with empty context


def test_today_format():
    journal = DailyJournal.__new__(DailyJournal)
    today = DailyJournal._today()
    assert len(today) == 10  # DD/MM/YYYY


def test_start_configures_scheduler():
    config, llm, llm_secondary, emotion, memory = make_deps(journal_time="22:30")
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    with patch("bot.intelligence.journal.AsyncIOScheduler") as MockScheduler:
        mock_sched = MagicMock()
        MockScheduler.return_value = mock_sched
        journal.start()
        # Two jobs: generate_and_send (journal) + run_memory_cleanup (cleanup 30min before)
        assert mock_sched.add_job.call_count == 2
        journal_call = mock_sched.add_job.call_args_list[0]
        assert journal_call.kwargs.get("hour") == 22
        assert journal_call.kwargs.get("minute") == 30
        cleanup_call = mock_sched.add_job.call_args_list[1]
        assert cleanup_call.kwargs.get("hour") == 22
        assert cleanup_call.kwargs.get("minute") == 0
        mock_sched.start.assert_called_once()


@pytest.mark.asyncio
async def test_build_context_text_multi_pass():
    """When messages exceed token threshold, uses multi-pass summarization."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)

    call_count = 0

    async def fake_complete(system, messages, purpose="summary"):
        nonlocal call_count
        call_count += 1
        return f"chunk_{call_count}"

    llm_secondary.complete = fake_complete

    # 35 messages × 1000 chars = 35000 chars → 8750 tokens > 6000 threshold
    # 35 messages → 2 chunks (30 + 5) → 2 chunk summaries + 1 final = 3 calls
    big_messages = [
        {"author": "User", "content": "x" * 1000, "timestamp": float(i)}
        for i in range(35)
    ]
    result = await journal._build_context_text(big_messages)

    assert call_count == 3
    assert result == "chunk_3"  # the final combining call


# ── Arc émotionnel ────────────────────────────────────────────────────────────

def test_build_emotion_arc_returns_empty_with_less_than_2_snapshots():
    from bot.intelligence.journal import _build_emotion_arc
    assert _build_emotion_arc([]) == ""
    assert _build_emotion_arc([{"snapshot_at": 0, "anger": 0.5, "joy": 0.0,
                                "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}]) == ""


def test_build_emotion_arc_formats_dominant_emotions():
    from bot.intelligence.journal import _build_emotion_arc
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
    assert "pic de joie" in arc       # 0.75 → 75% ≥ 70% → "pic de"
    assert "joie montante" in arc     # 0.55 → 55% ≥ 50% → "montante"
    assert "curiosité légère" in arc  # 0.35 → 35% ≥ 30% et < 50% → "légère"
    assert arc.count("\n") >= 1


def test_build_emotion_arc_omits_emotions_below_30_percent():
    from bot.intelligence.journal import _build_emotion_arc
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
    from bot.intelligence.journal import _build_emotion_arc
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
    config, llm, llm_secondary, emotion, memory = make_deps()
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)  # pas de db
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_journal_emotions_text_uses_percentage():
    """Le prompt du journal contient les émotions en pourcentage."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    # joy=0.5 → 50%
    emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    captured_prompt = []

    async def capture(system, messages, purpose="", **kwargs):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    llm.complete = capture
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
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
    from datetime import datetime
    from zoneinfo import ZoneInfo
    db = await Database.create(str(tmp_path / "test.db"))

    # Insérer 2 snapshots après minuit aujourd'hui (évite le flaky quand l'heure est proche de minuit)
    midnight = datetime.now(ZoneInfo("Europe/Paris")).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.8, 0.0, 0.0, 0.0)",
        (midnight + 3600,),
    )
    await db.execute(
        "INSERT INTO emotion_history (snapshot_at, anger, joy, sadness, curiosity, boredom) "
        "VALUES (?, 0.0, 0.5, 0.0, 0.0, 0.0)",
        (midnight + 7200,),
    )

    config, llm, llm_secondary, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose="", **kwargs):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    llm.complete = capture
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" in final_prompt
    await db.close()


@pytest.mark.asyncio
async def test_journal_arc_absent_when_less_than_2_snapshots(tmp_path):
    """Avec 0 ou 1 snapshot, l'arc est absent du prompt (pas de ligne vide parasite)."""
    from bot.db.database import Database
    db = await Database.create(str(tmp_path / "test.db"))

    config, llm, llm_secondary, emotion, memory = make_deps()
    captured_prompt = []

    async def capture(system, messages, purpose="", **kwargs):
        captured_prompt.append(messages[0]["content"])
        return "Journal text"

    llm.complete = capture
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    sent = []
    journal.set_send_callback(AsyncMock(side_effect=lambda t, **kw: sent.append(t)))
    await journal.generate_and_send()

    final_prompt = captured_prompt[-1]
    assert "Arc émotionnel" not in final_prompt
    await db.close()


# ── 4-source fallback chain ────────────────────────────────────────────────────

def make_deps_with_db(journal_channel_id=12345, journal_time="03:00",
                      db_messages=None):
    config, llm, llm_secondary, emotion, memory = make_deps(journal_channel_id, journal_time)
    config.bot.emotion_peak_threshold = 0.7
    memory.get_all_contexts = MagicMock(return_value=[])  # RAM vide

    db = MagicMock()
    if db_messages is None:
        db_messages = [
            {"author": "Alice", "content": "Hello from DB", "timestamp": 1000.0},
        ]
    db.get_today_messages = AsyncMock(return_value=db_messages)
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.get_emotion_peaks_since = AsyncMock(return_value=[])
    db.get_emotion_averages = AsyncMock(return_value=None)
    db.get_yesterday_journal = AsyncMock(return_value=None)
    db.insert_journal = AsyncMock()
    db.list_memory_users = AsyncMock(return_value=[])

    return config, llm, llm_secondary, emotion, memory, db


def _get_journal_user_msg(llm_mock) -> str:
    """Extrait le contenu du message utilisateur envoyé lors du dernier appel journal."""
    if llm_mock.complete.called:
        call_args = llm_mock.complete.call_args_list
        journal_call = [c for c in call_args if c.kwargs.get("purpose") == "daily_journal"]
        if journal_call:
            return journal_call[0].args[1][0]["content"]
    return ""


@pytest.mark.asyncio
async def test_journal_uses_db_messages_when_available():
    """Le journal doit utiliser daily_log quand des messages sont disponibles."""
    config, llm, llm_secondary, emotion, memory, db = make_deps_with_db()
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    assert "Hello from DB" in _get_journal_user_msg(llm)


@pytest.mark.asyncio
async def test_journal_falls_back_to_discord_history_when_db_empty():
    """Quand daily_log vide, le journal doit utiliser le callback Discord history."""
    config, llm, llm_secondary, emotion, memory, db = make_deps_with_db(db_messages=[])
    history_messages = [
        {"author": "Bob", "content": "Message depuis Discord history", "timestamp": 2000.0},
    ]
    history_cb = AsyncMock(return_value=history_messages)

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db)
    journal.set_send_callback(AsyncMock())
    journal.set_history_callback(history_cb)

    await journal.generate_and_send()

    history_cb.assert_called_once()
    assert "Message depuis Discord history" in _get_journal_user_msg(llm)


@pytest.mark.asyncio
async def test_journal_falls_back_to_ram_when_no_db_no_history():
    """Sans db et sans history callback, le journal utilise get_all_contexts() (RAM)."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    # memory.get_all_contexts retourne des messages (défini dans make_deps)
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=None)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    llm.complete.assert_called()


@pytest.mark.asyncio
async def test_journal_uses_mem0_fallback_when_all_sources_empty():
    """Quand toutes les sources sont vides, le journal utilise les souvenirs mem0."""
    config, llm, llm_secondary, emotion, memory, db = make_deps_with_db(db_messages=[])
    history_cb = AsyncMock(return_value=[])  # Discord history vide aussi
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:123", "platform": "discord", "username": "Alice"}
    ])
    memory.get_all = AsyncMock(return_value="Alice aime les chats.")

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db)
    journal.set_send_callback(AsyncMock())
    journal.set_history_callback(history_cb)

    await journal.generate_and_send()

    assert "Alice aime les chats." in _get_journal_user_msg(llm)


@pytest.mark.asyncio
async def test_journal_includes_twitch_visits_block():
    """Le journal doit inclure les visites Twitch dans son prompt si elles existent."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    db = MagicMock()
    db.get_today_messages = AsyncMock(return_value=[])
    db.get_emotion_peaks_since = AsyncMock(return_value=[])
    db.get_emotion_snapshots_since = AsyncMock(return_value=[])
    db.get_emotion_averages = AsyncMock(return_value={})
    db.get_yesterday_journal = AsyncMock(return_value=None)
    db.get_gallery_images_for_date = AsyncMock(return_value=[])
    db.insert_journal = AsyncMock()
    db.get_twitch_visits_for_date = AsyncMock(return_value=[
        {
            "channel": "azrael",
            "joined_at": 1000.0,
            "left_at": 1000.0 + 2700,
            "duration_s": 2700,
            "msg_count": 34,
            "summary": "Chez Azrael, ambiance chill, un sub pendant ma visite.",
        }
    ])

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    # Vérifier que le prompt envoyé au LLM contient le bloc visites
    call_args = llm.complete.call_args
    user_msg = call_args[0][1][0]["content"]  # messages[0]["content"]
    assert "azrael" in user_msg.lower()
    assert "45 min" in user_msg
    assert "Chez Azrael" in user_msg


# ── _emotion_tone_hint ────────────────────────────────────────────────────────

from bot.intelligence.journal import _emotion_tone_hint


def test_emotion_tone_hint_anger():
    emotions = {"anger": 0.72, "joy": 0.1, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "colère" in hint
    assert "72%" in hint
    assert "court" in hint.lower() or "cassant" in hint.lower()


def test_emotion_tone_hint_joy():
    emotions = {"anger": 0.0, "joy": 0.65, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "joyeux" in hint
    assert "65%" in hint


def test_emotion_tone_hint_sadness():
    emotions = {"anger": 0.0, "joy": 0.1, "sadness": 0.55, "curiosity": 0.0, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "tristesse" in hint
    assert "55%" in hint


def test_emotion_tone_hint_curiosity():
    emotions = {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.80, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert "curiosité" in hint
    assert "80%" in hint


def test_emotion_tone_hint_boredom():
    emotions = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.1, "boredom": 0.45}
    hint = _emotion_tone_hint(emotions)
    assert "ennui" in hint
    assert "45%" in hint


def test_emotion_tone_hint_below_threshold():
    """Aucune émotion ≥ 0.30 → pas de signal."""
    emotions = {"anger": 0.1, "joy": 0.2, "sadness": 0.05, "curiosity": 0.15, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert hint == ""


def test_emotion_tone_hint_exactly_at_threshold():
    """Valeur exactement à 0.30 → signal activé."""
    emotions = {"anger": 0.0, "joy": 0.30, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    hint = _emotion_tone_hint(emotions)
    assert hint != ""
    assert "30%" in hint


@pytest.mark.asyncio
async def test_emotion_hint_injected_in_prompt_when_dominant():
    """Quand une émotion domine (≥ 0.30), le hint est dans le user message envoyé au LLM."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.75, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    call_args = llm.complete.call_args
    user_messages = call_args[0][1]  # second positional arg = messages list
    user_content = " ".join(m["content"] for m in user_messages if m["role"] == "user")
    # Le hint directif doit être présent avec "Ce soir ta colère domine (75%)"
    assert "Ce soir ta colère domine" in user_content
    assert "75%" in user_content


@pytest.mark.asyncio
async def test_emotion_hint_absent_when_no_dominant():
    """Quand aucune émotion ≥ 0.30, aucun hint de ton dans le user message."""
    config, llm, llm_secondary, emotion, memory = make_deps()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.2, "sadness": 0.05, "curiosity": 0.15, "boredom": 0.0}
    )
    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    journal.set_send_callback(AsyncMock())

    await journal.generate_and_send()

    call_args = llm.complete.call_args
    user_messages = call_args[0][1]
    user_content = " ".join(m["content"] for m in user_messages if m["role"] == "user")
    # Aucune des directives de ton ne doit apparaître (chercher les débuts des hints)
    assert "Ce soir ta colère domine" not in user_content
    assert "Ce soir tu es plutôt joyeux" not in user_content
    assert "Ce soir ta tristesse domine" not in user_content
    assert "Ce soir ta curiosité domine" not in user_content
    assert "Ce soir c'est l'ennui qui domine" not in user_content
