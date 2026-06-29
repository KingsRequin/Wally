from unittest.mock import MagicMock
from bot.intelligence.journal import DailyJournal


def _journal():
    config = MagicMock()
    config.bot.journal_time = "21:00"
    return DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), db=MagicMock())


def test_set_user_modeler_then_start_registers_job():
    j = _journal()
    j.set_user_modeler(MagicMock())
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "user_model_refresh" in ids


def test_start_without_user_modeler_has_no_job():
    j = _journal()
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "user_model_refresh" not in ids
