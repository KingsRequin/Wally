# tests/test_apex_accounts_db.py
"""Tests pour la table apex_accounts et ses méthodes DB.

Elle existe parce que rien ne reliait quelqu'un à son compte Apex : le 2026-08-07,
Wally a redemandé trois fois de suite son pseudo et sa plateforme à xeforce_.

La base passe par une fixture : sans `close()`, le thread d'aiosqlite survit au
test et fait pendre pytest — ce qui arrive dès qu'une assertion échoue avant la
fermeture écrite à la main.
"""
import pytest_asyncio

import pytest

from bot.db.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest.mark.asyncio
async def test_lier_puis_relire(db):
    await db.apex_link_account(
        identity="twitch:123", display_name="xeforce_",
        apex_name="IBrainroTI67", apex_platform="PC", uid="42",
    )
    compte = await db.apex_get_account("twitch:123")
    assert compte["apex_name"] == "IBrainroTI67"
    assert compte["apex_platform"] == "PC"
    assert compte["uid"] == "42"


@pytest.mark.asyncio
async def test_relier_remplace_l_ancien(db):
    """Un compte Apex par personne : le dernier déclaré fait foi."""
    await db.apex_link_account(
        identity="twitch:123", display_name="xeforce_",
        apex_name="AncienPseudo", apex_platform="PC", uid=None,
    )
    await db.apex_link_account(
        identity="twitch:123", display_name="xeforce_",
        apex_name="NouveauPseudo", apex_platform="PS4", uid="99",
    )
    compte = await db.apex_get_account("twitch:123")
    assert compte["apex_name"] == "NouveauPseudo"
    assert compte["apex_platform"] == "PS4"


@pytest.mark.asyncio
async def test_retrouver_par_pseudo_de_plateforme(db):
    """« les stats de xeforce » doit tomber sur le compte qu'il a déclaré."""
    await db.apex_link_account(
        identity="twitch:123", display_name="xeforce_",
        apex_name="IBrainroTI67", apex_platform="PC", uid=None,
    )
    trouve = await db.apex_find_by_display_name("XEFORCE_")   # la casse est ignorée
    assert trouve["apex_name"] == "IBrainroTI67"


@pytest.mark.asyncio
async def test_inconnu_ne_rend_rien(db):
    assert await db.apex_get_account("twitch:inconnu") is None
    assert await db.apex_find_by_display_name("personne") is None
