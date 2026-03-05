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
    memory._context_windows = {
        "ch1": [
            {"author": "Alice", "content": "Hello", "timestamp": 1000.0},
            {"author": "Wally", "content": "Hi Alice!", "timestamp": 1001.0},
        ]
    }

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
    memory._context_windows = {}
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
