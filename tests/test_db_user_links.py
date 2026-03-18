# tests/test_db_user_links.py
"""Tests pour la table user_links et ses méthodes DB."""
import pytest
from bot.db.database import Database


@pytest.mark.asyncio
async def test_upsert_and_list_proposals(tmp_path):
    """upsert crée une entrée pending, list_link_proposals la retourne."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.85)
    proposals = await db.list_link_proposals()
    assert len(proposals) == 1
    p = proposals[0]
    assert p["canonical_id"] == "discord:123"
    assert p["alias_id"] == "twitch:abc"
    assert p["confidence"] == pytest.approx(0.85)
    assert p["status"] == "pending"
    await db.close()


@pytest.mark.asyncio
async def test_upsert_updates_existing(tmp_path):
    """Upsert sur la même paire met à jour la confidence."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.75)
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.90)
    proposals = await db.list_link_proposals()
    assert len(proposals) == 1
    assert proposals[0]["confidence"] == pytest.approx(0.90)
    await db.close()


@pytest.mark.asyncio
async def test_accept_link(tmp_path):
    """accept_link passe le statut à accepted et retourne les IDs."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.85)
    proposals = await db.list_link_proposals()
    link_id = proposals[0]["id"]
    result = await db.accept_link(link_id)
    assert result["canonical_id"] == "discord:123"
    assert result["alias_id"] == "twitch:abc"
    accepted = await db.list_link_proposals(status="accepted")
    assert len(accepted) == 1
    await db.close()


@pytest.mark.asyncio
async def test_reject_link(tmp_path):
    """reject_link passe le statut à rejected."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.85)
    proposals = await db.list_link_proposals()
    link_id = proposals[0]["id"]
    await db.reject_link(link_id)
    rejected = await db.list_link_proposals(status="rejected")
    assert len(rejected) == 1
    pending = await db.list_link_proposals(status="pending")
    assert len(pending) == 0
    await db.close()


@pytest.mark.asyncio
async def test_get_alias_map(tmp_path):
    """get_alias_map retourne seulement les liaisons acceptées."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:123", "twitch:abc", 0.85)
    await db.upsert_link_proposal("discord:456", "twitch:def", 0.70)
    proposals = await db.list_link_proposals()
    await db.accept_link(proposals[0]["id"])
    alias_map = await db.get_alias_map()
    assert len(alias_map) == 1
    assert alias_map["twitch:abc"] == "discord:123"
    await db.close()


@pytest.mark.asyncio
async def test_list_filter_by_status(tmp_path):
    """list_link_proposals filtre correctement par status."""
    db = await Database.create(str(tmp_path / "test.db"))
    await db.upsert_link_proposal("discord:1", "twitch:a", 0.9)
    await db.upsert_link_proposal("discord:2", "twitch:b", 0.8)
    proposals = await db.list_link_proposals()
    await db.accept_link(proposals[0]["id"])
    await db.reject_link(proposals[1]["id"])
    assert len(await db.list_link_proposals(status="pending")) == 0
    assert len(await db.list_link_proposals(status="accepted")) == 1
    assert len(await db.list_link_proposals(status="rejected")) == 1
    await db.close()
