"""Tests Phase 6 — registre des demandes d'amélioration (pending_upgrades)."""
import aiosqlite
import pytest

from bot.intelligence.upgrade_registry import (
    UpgradeRegistry, REQUESTED, DELIVERED, DECLINED, ABANDONED,
)


async def _make_db(tmp_path):
    db = str(tmp_path / "u.db")
    async with aiosqlite.connect(db) as c:
        await c.execute(
            """CREATE TABLE pending_upgrades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal TEXT NOT NULL, message_id TEXT, dm_channel_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, decided_at TEXT)"""
        )
        await c.commit()
    return db


@pytest.mark.asyncio
async def test_record_and_recent(tmp_path):
    reg = UpgradeRegistry(await _make_db(tmp_path))
    uid = await reg.record_request("voir les réactions emoji sur les messages")
    assert uid >= 1
    rows = await reg.recent()
    assert len(rows) == 1
    assert rows[0].status == REQUESTED
    assert "réactions" in rows[0].proposal


@pytest.mark.asyncio
async def test_set_status_transitions(tmp_path):
    reg = UpgradeRegistry(await _make_db(tmp_path))
    uid = await reg.record_request("parler en vocal")
    await reg.set_status(uid, DELIVERED)
    rows = await reg.recent()
    assert rows[0].status == DELIVERED
    assert rows[0].decided_at is not None


@pytest.mark.asyncio
async def test_find_similar_blocks_requested_and_delivered(tmp_path):
    reg = UpgradeRegistry(await _make_db(tmp_path))
    await reg.record_request("voir les réactions emoji des gens sur mes messages")
    # paraphrase proche -> match
    hit = await reg.find_similar("avoir accès aux réactions emoji sur les messages récents")
    assert hit is not None
    # sujet sans rapport -> pas de match
    assert await reg.find_similar("apprendre à jouer aux échecs") is None


@pytest.mark.asyncio
async def test_find_similar_ignores_abandoned(tmp_path):
    reg = UpgradeRegistry(await _make_db(tmp_path))
    uid = await reg.record_request("scraper le site AniList pour les animés")
    await reg.set_status(uid, ABANDONED)
    # une demande abandonnée ne bloque pas une nouvelle tentative
    assert await reg.find_similar("scraper AniList pour récupérer les animés") is None


@pytest.mark.asyncio
async def test_find_similar_ignores_declined(tmp_path):
    reg = UpgradeRegistry(await _make_db(tmp_path))
    uid = await reg.record_request("envoyer des memes générés")
    await reg.set_status(uid, DECLINED)
    # declined n'est pas bloquant ici (le set _declined de SelfFix gère ce cas)
    assert await reg.find_similar("générer et envoyer des memes") is None
