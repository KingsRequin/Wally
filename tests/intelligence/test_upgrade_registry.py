"""Tests Phase 6 — registre des demandes d'amélioration (pending_upgrades)."""
import pytest

from bot.intelligence.upgrade_registry import (
    ABANDONED,
    DECLINED,
    DELIVERED,
    REQUESTED,
    UpgradeRegistry,
)


async def _make_db(tmp_path):
    """Base au VRAI schéma. Un DDL recopié à la main ici avait dérivé du schéma
    réel (colonne `capability` ajoutée le 2026-08-09) et cassait `recent()`."""
    from bot.db.schema_v2 import create_v2_tables

    db = str(tmp_path / "u.db")
    await create_v2_tables(db)
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
async def test_find_similar_bloque_un_refus(tmp_path):
    """DECLINED bloque DURABLEMENT : le `set` en mémoire de SelfFix ne survivait
    pas au redémarrage, alors que le DM promet « je ne te le reproposerai pas »."""
    reg = UpgradeRegistry(await _make_db(tmp_path))
    uid = await reg.record_request("envoyer des memes générés")
    await reg.set_status(uid, DECLINED)
    hit = await reg.find_similar("générer et envoyer des memes")
    assert hit is not None and hit.status == DECLINED
