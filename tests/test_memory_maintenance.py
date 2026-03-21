# tests/test_memory_maintenance.py
import time
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_insert_and_get_pending_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "déménage le 1er", "Quel mois ?", "high")
    q = await db.get_pending_question("discord:123")
    assert q is not None
    assert q["question"] == "Quel mois ?"
    assert q["priority"] == "high"
    assert q["attempts"] == 0
    assert q["resolved"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_priority_order(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Low question", "low")
    await db.insert_memory_question("discord:123", "mem2", "High question", "high")
    await db.insert_memory_question("discord:123", "mem3", "Medium question", "medium")
    q = await db.get_pending_question("discord:123")
    assert q["question"] == "High question"
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_none_when_empty(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    q = await db.get_pending_question("discord:999")
    assert q is None
    await db.close()


@pytest.mark.asyncio
async def test_increment_attempts(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    await db.increment_question_attempts(q["id"])
    q2 = await db.get_pending_question("discord:123")
    assert q2["attempts"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_max_attempts_excludes_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    for _ in range(3):
        await db.increment_question_attempts(q["id"])
    q2 = await db.get_pending_question("discord:123", max_attempts=3)
    assert q2 is None
    await db.close()


@pytest.mark.asyncio
async def test_resolve_question(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem", "Question?", "high")
    q = await db.get_pending_question("discord:123")
    await db.resolve_question(q["id"])
    q2 = await db.get_pending_question("discord:123")
    assert q2 is None
    await db.close()


@pytest.mark.asyncio
async def test_get_all_pending_questions(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Q1?", "high")
    await db.insert_memory_question("discord:123", "mem2", "Q2?", "low")
    await db.insert_memory_question("discord:456", "mem3", "Q3?", "medium")
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 2
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_questions(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.execute(
        "INSERT INTO memory_questions (user_id, memory_text, question, priority, attempts, resolved, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("discord:123", "mem", "Old Q?", "low", 0, 1, time.time() - 40 * 86400),
    )
    await db.insert_memory_question("discord:123", "mem2", "New Q?", "high")
    await db.cleanup_old_questions(max_age_days=30)
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 1
    assert qs[0]["question"] == "New Q?"
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_old_questions_purges_unresolved_old(tmp_path):
    """Old unresolved questions (> max_age_days) should also be purged."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.execute(
        "INSERT INTO memory_questions (user_id, memory_text, question, priority, attempts, resolved, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("discord:123", "mem", "Old unresolved Q?", "high", 2, 0, time.time() - 40 * 86400),
    )
    await db.cleanup_old_questions(max_age_days=30)
    qs = await db.get_all_pending_questions("discord:123")
    assert len(qs) == 0
    await db.close()


from unittest.mock import MagicMock, AsyncMock, patch
from bot.core.memory import MemoryService


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = 15
    config.openai.secondary_model = "gpt-4o-mini"
    return config


@pytest.mark.asyncio
async def test_evaluate_memory_incomplete_creates_question(tmp_path):
    """When LLM says memory is incomplete, questions are inserted in DB."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value='{"complete": false, "questions": [{"question": "Quel mois ?", "priority": "high"}], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "déménage le 1er")

    q = await db.get_pending_question("discord:123")
    assert q is not None
    assert q["question"] == "Quel mois ?"
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_complete_no_question(tmp_path):
    """When LLM says memory is complete, no question is created."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value='{"complete": true, "questions": [], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "Habite à Lyon depuis 2020")

    q = await db.get_pending_question("discord:123")
    assert q is None
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_resolves_existing_questions(tmp_path):
    """When LLM says new memory resolves an existing question, it's marked resolved."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    await db.insert_memory_question("discord:123", "déménage le 1er", "Quel mois ?", "high")
    q = await db.get_pending_question("discord:123")
    qid = q["id"]

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(
        return_value=f'{{"complete": true, "questions": [], "resolves": [{qid}]}}'
    )
    svc.set_openai_client(mock_openai)

    await svc._evaluate_memory("discord:123", "Déménage le 1er mars 2026 à Lyon")

    q2 = await db.get_pending_question("discord:123")
    assert q2 is None  # resolved
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_handles_invalid_json(tmp_path):
    """Invalid JSON from LLM should not crash."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value="not valid json")
    svc.set_openai_client(mock_openai)

    # Should not raise
    await svc._evaluate_memory("discord:123", "some memory")
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_returns_directive(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    await db.insert_memory_question("discord:123", "mem", "Quel mois ?", "high")
    directive = await svc.get_pending_question_directive("discord", "123")
    assert "Quel mois ?" in directive
    assert "Si l'occasion se présente" in directive

    # Check attempts was incremented
    q = await db.get_pending_question("discord:123")
    assert q["attempts"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_empty_when_none(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    directive = await svc.get_pending_question_directive("discord", "999")
    assert directive == ""
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_no_db(tmp_path):
    svc = MemoryService(make_config())
    # No db set
    directive = await svc.get_pending_question_directive("discord", "123")
    assert directive == ""
