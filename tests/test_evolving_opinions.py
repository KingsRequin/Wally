# tests/test_evolving_opinions.py
import time

import pytest

from bot.db.database import Database


@pytest.mark.asyncio
async def test_upsert_opinion_creates(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_opinion("Valorant", "Jeu de camping glorifié.")
    opinions = await db.get_opinions()
    assert len(opinions) == 1
    assert opinions[0]["topic"] == "Valorant"
    assert "camping" in opinions[0]["opinion"]
    await db.close()


@pytest.mark.asyncio
async def test_upsert_opinion_updates_existing(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_opinion("Valorant", "Pas terrible.")
    await db.upsert_opinion("Valorant", "En fait c'est nul.")
    opinions = await db.get_opinions()
    assert len(opinions) == 1
    assert "nul" in opinions[0]["opinion"]
    await db.close()


@pytest.mark.asyncio
async def test_get_opinions_returns_latest(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    for i in range(12):
        await db.upsert_opinion(f"sujet_{i}", f"opinion {i}")
    opinions = await db.get_opinions(limit=10)
    assert len(opinions) == 10
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_removes_old(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_opinion("vieux", "ancien avis")
    # Backdate
    old_time = time.time() - 31 * 86400
    await db.execute(
        "UPDATE opinions SET updated_at=? WHERE topic=?",
        (old_time, "vieux"),
    )
    await db.upsert_opinion("récent", "avis frais")
    await db.cleanup_opinions(max_age_days=30, max_count=10)
    opinions = await db.get_opinions()
    assert len(opinions) == 1
    assert opinions[0]["topic"] == "récent"
    await db.close()


@pytest.mark.asyncio
async def test_cleanup_keeps_max_count(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    for i in range(15):
        await db.upsert_opinion(f"topic_{i}", f"opinion {i}")
    await db.cleanup_opinions(max_age_days=30, max_count=10)
    opinions = await db.get_opinions(limit=20)
    assert len(opinions) == 10
    await db.close()


@pytest.mark.asyncio
async def test_get_opinions_empty(tmp_path):
    db = await Database.create(str(tmp_path / "test.db"))
    opinions = await db.get_opinions()
    assert opinions == []
    await db.close()
