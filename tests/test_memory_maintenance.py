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


# ── Péremption des faits éphémères (expires_at) ────────────────────────────────


@pytest.mark.asyncio
async def test_expired_facts_excluded_from_recall_and_archived(tmp_path):
    """Un fait éphémère périmé n'est jamais rappelé, et archive_expired() l'archive."""
    from datetime import datetime, timedelta
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import (
        SQLiteFactStore, AtomicFact, FactCategory, FactStatus,
    )

    path = str(tmp_path / "facts.db")
    await create_v2_tables(path)
    store = SQLiteFactStore(path)
    now = datetime.utcnow()
    uid = "discord:1"

    await store.add(AtomicFact(user_id=uid, content="Azraël joue à Darktide",
                               category=FactCategory.FAIT, subject="Azraël",
                               predicate="plays", object_="Darktide"))
    await store.add(AtomicFact(user_id=uid, content="Azraël donne un tuto ce soir",
                               category=FactCategory.FAIT, subject="Azraël",
                               predicate="plans", object_="tuto",
                               expires_at=now - timedelta(hours=1)))

    # Rappel : le fait périmé est filtré en temps réel.
    hits = await store.search_fts(uid, "Azraël Darktide tuto", limit=10)
    contents = [f.content for f, _ in hits]
    assert "Azraël joue à Darktide" in contents
    assert all("tuto" not in c for c in contents)

    # Archivage : 1 fait périmé archivé, le durable reste actif.
    n = await store.archive_expired()
    assert n == 1
    active = await store.get_by_user(uid, status=FactStatus.ACTIVE)
    assert len(active) == 1 and active[0].content == "Azraël joue à Darktide"


