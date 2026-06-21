import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.persona_manager import PersonaManager, PersonaManagerError
from bot.intelligence.evolution_log import EvolutionLog


def _make_manager(tmp_path, llm_response=None, evolution_log=None):
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "SOUL.md").write_text("Old content " * 10, encoding="utf-8")
    (persona_dir / "EMOTIONS.md").write_text("Emotions " * 10, encoding="utf-8")

    # Default response: 121 chars vs 120-char SOUL — 0.8% change, within 20% budget
    if llm_response is None:
        llm_response = "Old content " * 10 + "!"
    log = evolution_log or EvolutionLog(tmp_path / "evolution_log.jsonl")
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_response)
    return PersonaManager(persona_dir, log, llm), persona_dir, log


@pytest.mark.asyncio
async def test_evolve_writes_new_content(tmp_path):
    new_text = "Old content " * 10 + "!"  # 121 chars — 0.8% change, within 20% SOUL budget
    manager, persona_dir, _ = _make_manager(tmp_path, llm_response=new_text)
    await manager.evolve("SOUL", "Wally veut être plus spontané")
    assert (persona_dir / "SOUL.md").read_text() == new_text


@pytest.mark.asyncio
async def test_evolve_logs_entry(tmp_path):
    manager, _, log = _make_manager(tmp_path)
    await manager.evolve("SOUL", "test change")
    assert log.count_today("SOUL") == 1


@pytest.mark.asyncio
async def test_guardrail_max_evolutions_per_day(tmp_path):
    manager, _, log = _make_manager(tmp_path)
    await manager.evolve("SOUL", "first change")
    with pytest.raises(PersonaManagerError, match="already evolved"):
        await manager.evolve("SOUL", "second change")


@pytest.mark.asyncio
async def test_guardrail_max_evolutions_restart_resilient(tmp_path):
    """Second PersonaManager instance (simulating restart) also blocked by log-based count."""
    log = EvolutionLog(tmp_path / "evolution_log.jsonl")
    manager1, persona_dir, _ = _make_manager(tmp_path, evolution_log=log,
                                              llm_response="Old content " * 10 + "!")
    await manager1.evolve("SOUL", "first change")

    # Simulate restart: new manager instance, same log
    llm2 = MagicMock()
    llm2.complete = AsyncMock(return_value="Old content " * 10 + "?")
    manager2 = PersonaManager(persona_dir, log, llm2)
    with pytest.raises(PersonaManagerError, match="already evolved"):
        await manager2.evolve("SOUL", "second change after restart")


@pytest.mark.asyncio
async def test_guardrail_max_change_percent(tmp_path):
    from bot.intelligence.evolution_log import EvolutionEntry
    from datetime import datetime, timezone
    log = EvolutionLog(tmp_path / "evolution_log.jsonl")
    # Simulate already 15% changed today for EMOTIONS (max is 15%)
    log.append(EvolutionEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        section="EMOTIONS",
        before_len=100,
        after_len=115,
        reason="prior change",
    ))
    manager, _, _ = _make_manager(tmp_path, evolution_log=log)
    with pytest.raises(PersonaManagerError, match="already changed"):
        await manager.evolve("EMOTIONS", "another change")


@pytest.mark.asyncio
async def test_evolve_unknown_section_raises(tmp_path):
    manager, _, _ = _make_manager(tmp_path)
    with pytest.raises(PersonaManagerError, match="Unknown section"):
        await manager.evolve("NONEXISTENT", "change")
