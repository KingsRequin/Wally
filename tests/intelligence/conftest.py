import asyncio
import os
import tempfile
import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def tmp_db_path():
    """Base de données SQLite temporaire, supprimée après le test."""
    from bot.db.schema_v2 import create_v2_tables
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    await create_v2_tables(path)
    yield path
    os.unlink(path)
