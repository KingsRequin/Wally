import pytest
from pathlib import Path
from datetime import date
from wally_v2.core.evolution_log import EvolutionLog, EvolutionEntry


def _make_log(tmp_path) -> EvolutionLog:
    return EvolutionLog(tmp_path / "evolution_log.jsonl")


def _entry(section="SOUL", before=100, after=105, reason="test") -> EvolutionEntry:
    from datetime import datetime, timezone
    return EvolutionEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        section=section,
        before_len=before,
        after_len=after,
        reason=reason,
    )


def test_append_and_entries_today(tmp_path):
    log = _make_log(tmp_path)
    e = _entry()
    log.append(e)
    entries = log.entries_today("SOUL")
    assert len(entries) == 1
    assert entries[0].section == "SOUL"
    assert entries[0].reason == "test"


def test_count_today(tmp_path):
    log = _make_log(tmp_path)
    log.append(_entry("SOUL"))
    log.append(_entry("SOUL"))
    log.append(_entry("EMOTIONS"))
    assert log.count_today("SOUL") == 2
    assert log.count_today("EMOTIONS") == 1
    assert log.count_today("WEEKDAYS") == 0


def test_change_percent_today(tmp_path):
    log = _make_log(tmp_path)
    # 100 → 120 = 20% change
    log.append(_entry(before=100, after=120))
    pct = log.change_percent_today("SOUL")
    assert abs(pct - 0.20) < 0.001


def test_entries_filtered_by_section(tmp_path):
    log = _make_log(tmp_path)
    log.append(_entry("SOUL"))
    log.append(_entry("EMOTIONS"))
    assert len(log.entries_today("EMOTIONS")) == 1
    assert log.entries_today("EMOTIONS")[0].section == "EMOTIONS"
