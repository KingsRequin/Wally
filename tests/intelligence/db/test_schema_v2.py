import pytest
import aiosqlite
import tempfile
import os

from bot.db.schema_v2 import create_v2_tables


@pytest.mark.asyncio
async def test_create_v2_tables_creates_all_tables():
    """create_v2_tables() crée les tables attendues et retire thoughts."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await create_v2_tables(db_path)
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        expected = {"atomic_facts", "fact_relations", "pending_upgrades", "session_analyses"}
        assert expected.issubset(tables)
        assert "thoughts" not in tables
    finally:
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_create_v2_tables_idempotent():
    """create_v2_tables() peut être appelé deux fois sans erreur (IF NOT EXISTS)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await create_v2_tables(db_path)
        await create_v2_tables(db_path)  # deuxième appel — ne doit pas lever
    finally:
        os.unlink(db_path)
