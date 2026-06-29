import pytest
from unittest.mock import MagicMock
from bot.intelligence.journal import DailyJournal


def _journal():
    config = MagicMock()
    config.bot.journal_time = "21:00"
    j = DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock(), db=MagicMock())
    return j


def test_set_consolidator_then_start_registers_job():
    j = _journal()
    consolidator = MagicMock()
    j.set_consolidator(consolidator)
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "memory_consolidation" in ids


def test_start_without_consolidator_has_no_consolidation_job():
    j = _journal()
    sched = MagicMock()
    j.start(scheduler=sched)
    ids = {c.kwargs.get("id") for c in sched.add_job.call_args_list}
    assert "memory_consolidation" not in ids
