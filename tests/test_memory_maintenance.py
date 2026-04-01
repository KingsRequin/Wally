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


@pytest.mark.asyncio
async def test_duplicate_question_ignored(tmp_path):
    """Inserting the same question twice should not create a duplicate."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.insert_memory_question("discord:123", "mem1", "Quel âge ?", "high")
    await db.insert_memory_question("discord:123", "mem2", "Quel âge ?", "medium")
    pending = await db.get_all_pending_questions("discord:123")
    assert len(pending) == 1, f"Expected 1 question, got {len(pending)}"
    await db.close()


@pytest.mark.asyncio
async def test_maintenance_lock_exists():
    """MemoryService should have a _maintenance_locks dict."""
    from unittest.mock import MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    assert hasattr(svc, "_maintenance_locks")
    assert isinstance(svc._maintenance_locks, dict)


from unittest.mock import MagicMock, AsyncMock, patch
from bot.core.memory import MemoryService
from bot.core.memory_store import MemoryRecord


@pytest.mark.asyncio
async def test_consolidate_updates_memory_count(tmp_path):
    """After consolidation, memory_count in DB should reflect the new Qdrant count."""
    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    uid = "discord:6105503330425897"

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    # Seed a memory user
    await db.upsert_memory_user(uid, "discord", "TestUser")
    await db.execute("UPDATE memory_users SET memory_count=30 WHERE user_id=?", (uid,))

    # Mock store to return count=1 after consolidation
    mock_store = AsyncMock()
    mock_store.count = AsyncMock(return_value=1)
    mock_store.upsert = AsyncMock()
    mock_store.delete_batch = AsyncMock(return_value=26)
    svc._store = mock_store

    # Mock LLM
    svc._openai = AsyncMock()
    svc._openai.complete = AsyncMock(return_value="- Fait consolidé 1\n- Fait consolidé 2")

    # Create fake records
    records = [MemoryRecord(id=str(i), text=f"Fact {i}", user_id=uid) for i in range(26)]

    await svc._consolidate(uid, records)

    # Verify memory_count was updated
    cursor = await db._conn.execute(
        "SELECT memory_count FROM memory_users WHERE user_id=?", (uid,)
    )
    row = await cursor.fetchone()
    assert row[0] == 1, f"Expected memory_count=1 after consolidation, got {row[0]}"

    await db.close()


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5
    return config


@pytest.mark.asyncio
async def test_evaluate_memory_incomplete_creates_question(tmp_path):
    """When LLM says memory is incomplete, questions are inserted in DB."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)
    svc._store_init_attempted = True
    svc._store = AsyncMock()
    svc._store.get_all = AsyncMock(return_value=[])

    mock_openai = MagicMock()
    mock_openai.complete = AsyncMock(return_value='{"complete": false, "questions": [{"question": "Quel mois ?", "priority": "high"}], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate("discord:123", "déménage le 1er")

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
    svc._store_init_attempted = True
    svc._store = AsyncMock()
    svc._store.get_all = AsyncMock(return_value=[])

    mock_openai = MagicMock()
    mock_openai.complete = AsyncMock(return_value='{"complete": true, "questions": [], "resolves": []}')
    svc.set_openai_client(mock_openai)

    await svc._evaluate("discord:123", "Habite à Lyon depuis 2020")

    q = await db.get_pending_question("discord:123")
    assert q is None
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_resolves_existing_questions(tmp_path):
    """When LLM says new memory resolves an existing question, it's marked resolved."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)
    svc._store_init_attempted = True
    svc._store = AsyncMock()
    svc._store.get_all = AsyncMock(return_value=[])

    await db.insert_memory_question("discord:123", "déménage le 1er", "Quel mois ?", "high")
    q = await db.get_pending_question("discord:123")
    qid = q["id"]

    mock_openai = MagicMock()
    mock_openai.complete = AsyncMock(
        return_value=f'{{"complete": true, "questions": [], "resolves": [{qid}]}}'
    )
    svc.set_openai_client(mock_openai)

    await svc._evaluate("discord:123", "Déménage le 1er mars 2026 à Lyon")

    q2 = await db.get_pending_question("discord:123")
    assert q2 is None  # resolved
    await db.close()


@pytest.mark.asyncio
async def test_evaluate_memory_handles_invalid_json(tmp_path):
    """Invalid JSON from LLM should not crash."""
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)
    svc._store_init_attempted = True
    svc._store = AsyncMock()
    svc._store.get_all = AsyncMock(return_value=[])

    mock_openai = MagicMock()
    mock_openai.complete = AsyncMock(return_value="not valid json")
    svc.set_openai_client(mock_openai)

    # Should not raise
    await svc._evaluate("discord:123", "some memory")
    await db.close()


@pytest.mark.asyncio
async def test_question_auto_resolved_by_semantic_match(tmp_path):
    """A pending question should be auto-resolved if a memory already answers it."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    uid = "discord:6105503330425897"

    # Insert a pending question
    await db.insert_memory_question(uid, "déménage bientôt", "Dans quelle ville ?", "high")

    # Mock store with a search that finds a matching memory
    mock_store = AsyncMock()
    mock_store.search = AsyncMock(return_value=[
        MagicMock(text="Déménage à Lyon en avril", score=0.90)
    ])
    svc._store = mock_store

    # Call get_pending_question_directive — should auto-resolve and return ""
    directive = await svc.get_pending_question_directive("discord", "6105503330425897")
    assert directive == "", f"Expected empty directive (auto-resolved), got: {directive}"

    # Verify question is resolved in DB
    q = await db.get_pending_question(uid)
    assert q is None, "Question should have been resolved"

    await db.close()


@pytest.mark.asyncio
async def test_question_not_resolved_by_low_score(tmp_path):
    """A pending question should NOT be auto-resolved if semantic score is below threshold."""
    from unittest.mock import AsyncMock, MagicMock
    from bot.core.memory import MemoryService

    config = MagicMock()
    config.bot.context_window_size = 5
    config.bot.context_token_threshold = 100
    config.bot.prelude_window_size = 15
    config.bot.memory_search_min_score = 0.5

    svc = MemoryService(config)
    db = await Database.create(str(tmp_path / "test.db"))
    svc._db = db

    uid = "discord:6105503330425897"
    await db.insert_memory_question(uid, "déménage bientôt", "Dans quelle ville ?", "high")

    mock_store = AsyncMock()
    mock_store.search = AsyncMock(return_value=[
        MagicMock(text="Aime les pizzas", score=0.40)
    ])
    svc._store = mock_store

    directive = await svc.get_pending_question_directive("discord", "6105503330425897")
    assert "Dans quelle ville" in directive
    await db.close()


@pytest.mark.asyncio
async def test_get_pending_question_directive_returns_directive(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    svc = MemoryService(make_config())
    svc.set_db(db)

    await db.insert_memory_question("discord:610550333042589752", "mem", "Quel mois ?", "high")
    directive = await svc.get_pending_question_directive("discord", "610550333042589752")
    assert "Quel mois ?" in directive
    assert "Si l'occasion se présente" in directive

    # Check attempts was incremented
    q = await db.get_pending_question("discord:610550333042589752")
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


from bot.core.journal import DailyJournal


def make_journal_deps(tmp_path, db=None):
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "21:00"
    llm = MagicMock()
    llm_secondary = MagicMock()
    emotion = MagicMock()
    memory = MagicMock()
    # Mock the store property to return an AsyncMock
    mock_store = AsyncMock()
    type(memory).store = property(lambda self: mock_store)
    memory._store_mock = mock_store  # keep reference for tests
    return config, llm, llm_secondary, emotion, memory


@pytest.mark.asyncio
async def test_memory_cleanup_deletes_expired(tmp_path):
    """Cleanup should delete memories identified as expired by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, llm, llm_secondary, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)

    # Register a user
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    # Mock store.get_all to return 6 memories as MemoryRecords
    fake_records = [
        MemoryRecord(id=f"id_{i}", text=f"Souvenir {i}", user_id="discord:123")
        for i in range(6)
    ]
    memory._store_mock.get_all = AsyncMock(return_value=fake_records)
    memory._store_mock.delete = AsyncMock()
    memory._store_mock.upsert = AsyncMock(return_value="new-id")

    # LLM says delete index 0 and 3
    llm_secondary.complete = AsyncMock(
        return_value='{"delete": [0, 3], "update": [], "questions": []}'
    )

    await journal.run_memory_cleanup()

    # Verify delete was called for id_0 and id_3
    delete_calls = [c.args[0] for c in memory._store_mock.delete.call_args_list]
    assert "id_0" in delete_calls
    assert "id_3" in delete_calls
    assert len(delete_calls) == 2
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_updates_memories(tmp_path):
    """Cleanup should update memories identified for reformulation by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, llm, llm_secondary, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    fake_records = [
        MemoryRecord(id=f"id_{i}", text=f"Souvenir {i}", user_id="discord:123")
        for i in range(6)
    ]
    memory._store_mock.get_all = AsyncMock(return_value=fake_records)
    memory._store_mock.delete = AsyncMock()
    memory._store_mock.upsert = AsyncMock(return_value="new-id")

    llm_secondary.complete = AsyncMock(
        return_value='{"delete": [], "update": [{"index": 1, "new_text": "Reformulé"}], "questions": []}'
    )

    await journal.run_memory_cleanup()

    # Old memory deleted
    memory._store_mock.delete.assert_called_once_with("id_1")
    # New text upserted
    memory._store_mock.upsert.assert_called_once()
    call_args = memory._store_mock.upsert.call_args
    assert call_args.args[1] == "Reformulé"
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_skips_few_memories(tmp_path):
    """Users with < 5 memories should be skipped."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, llm, llm_secondary, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    await db.upsert_memory_user("discord:123", "discord", "Alice")

    fake_records = [MemoryRecord(id="id_0", text="Only one", user_id="discord:123")]
    memory._store_mock.get_all = AsyncMock(return_value=fake_records)

    llm_secondary.complete = AsyncMock()

    await journal.run_memory_cleanup()

    # LLM should NOT have been called
    llm_secondary.complete.assert_not_called()
    await db.close()


@pytest.mark.asyncio
async def test_memory_cleanup_creates_questions(tmp_path):
    """Cleanup should create questions identified by LLM."""
    db = await Database.create(str(tmp_path / "test.db"))
    config, llm, llm_secondary, emotion, memory = make_journal_deps(tmp_path)

    journal = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    await db.upsert_memory_user("discord:610550333042589752", "discord", "Alice")

    fake_records = [
        MemoryRecord(id=f"id_{i}", text=f"Souvenir {i}", user_id="discord:610550333042589752")
        for i in range(6)
    ]
    memory._store_mock.get_all = AsyncMock(return_value=fake_records)
    memory._store_mock.delete = AsyncMock()

    llm_secondary.complete = AsyncMock(
        return_value='{"delete": [], "update": [], "questions": [{"question": "Depuis quand ?", "priority": "medium"}]}'
    )

    await journal.run_memory_cleanup()

    q = await db.get_pending_question("discord:610550333042589752")
    assert q is not None
    assert q["question"] == "Depuis quand ?"
    await db.close()
