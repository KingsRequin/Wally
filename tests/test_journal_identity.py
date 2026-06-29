# tests/test_journal_identity.py
"""Test that DailyJournal renders prompts/header/opinions with the correct bot name.

Red path (before fix): constants are rendered at module import with "Wally" hardcoded.
Green path (after fix): render_identity() is called at runtime, using the current identity.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence import identity


def _make_cindy_journal():
    """Build a DailyJournal instance configured for a 'Cindy' bot."""
    from bot.config import BotConfig
    from bot.intelligence.journal import DailyJournal

    cfg_obj = BotConfig(
        name="Cindy",
        trigger_names=["cindy"],
        language_default="fr",
        context_window_size=20,
        context_token_threshold=3000,
        journal_time="21:00",
    )
    # Set identity so render_identity() returns "Cindy"
    identity.set_identity(cfg_obj)

    config = MagicMock()
    config.bot = cfg_obj  # real BotConfig so config.bot.name == "Cindy"
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "21:00"
    config.bot.emotion_peak_threshold = 0.7

    llm = MagicMock()
    llm.complete = AsyncMock(return_value="Texte du journal.")

    llm_secondary = MagicMock()
    llm_secondary.complete = AsyncMock(return_value="Texte secondaire.")

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )

    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[
        {"author": "Alice", "content": "Hello", "timestamp": 1000.0, "platform": "discord"},
        {"author": "Cindy", "content": "Bonjour!", "timestamp": 1001.0, "platform": "discord"},
    ])

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory)
    return journal


@pytest.mark.asyncio
async def test_journal_system_prompt_uses_cindy_not_wally():
    """_JOURNAL_SYSTEM passed to LLM must contain 'Cindy', not 'Wally' or '{{BOT_NAME}}'."""
    journal = _make_cindy_journal()

    sent_messages = []
    journal.set_send_callback(AsyncMock(side_effect=lambda text, **kw: sent_messages.append(text)))

    await journal.generate_and_send()

    # The first call to llm.complete carries _JOURNAL_SYSTEM (rendered)
    assert journal._llm.complete.called
    first_call_args = journal._llm.complete.call_args
    system_prompt = first_call_args[0][0]  # positional arg 0 = system

    assert "Cindy" in system_prompt, f"Expected 'Cindy' in system prompt, got: {system_prompt!r}"
    assert "Wally" not in system_prompt, f"'Wally' should not appear in rendered system prompt"
    assert "{{BOT_NAME}}" not in system_prompt, f"Unrendered sentinel found in system prompt"


@pytest.mark.asyncio
async def test_journal_header_uses_cindy_not_wally():
    """The Discord header '# Journal de ...' must use config.bot.name, not hardcoded 'Wally'."""
    journal = _make_cindy_journal()

    sent_messages = []
    journal.set_send_callback(AsyncMock(side_effect=lambda text, **kw: sent_messages.append(text)))

    await journal.generate_and_send()

    assert sent_messages, "Expected at least one sent message"
    header = sent_messages[0]
    assert "Cindy" in header, f"Expected 'Cindy' in header, got: {header!r}"
    assert "Wally" not in header, f"'Wally' should not appear in the Discord header"


@pytest.mark.asyncio
async def test_topics_system_prompt_uses_cindy_not_wally():
    """_form_topics system_prompt (from topic_formation.md) must render {{BOT_NAME}} as 'Cindy'."""
    journal = _make_cindy_journal()

    # Provide a db mock for topic storage
    db = MagicMock()
    db.get_topics = AsyncMock(return_value=[])
    db.upsert_topic = AsyncMock()
    db.cleanup_topics = AsyncMock()
    db.insert_journal = AsyncMock()
    db.get_emotion_snapshots_for_date = AsyncMock(return_value=[])
    db.get_yesterday_journal = AsyncMock(return_value=None)
    db.get_journals_last_n_days = AsyncMock(return_value=[])
    db.get_gallery_images_for_date = AsyncMock(return_value=[])
    db.get_twitch_visits_for_date = AsyncMock(return_value=[])
    db.get_emotion_weekly_avg = AsyncMock(return_value=None)
    journal._db = db

    journal._llm_secondary.complete_structured = AsyncMock(return_value={"topics": []})

    await journal._form_topics("résumé de test")

    assert journal._llm_secondary.complete_structured.called, "Expected complete_structured to be called"
    system_prompt = journal._llm_secondary.complete_structured.call_args[0][0]

    assert "Cindy" in system_prompt, f"Expected 'Cindy' in topic_formation prompt, got: {system_prompt!r}"
    assert "Wally" not in system_prompt, f"'Wally' should not appear in rendered topic prompt"
    assert "{{BOT_NAME}}" not in system_prompt, "Unrendered sentinel found in topic system prompt"
