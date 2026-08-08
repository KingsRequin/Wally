# tests/test_apex_seed_accounts.py
"""Les comptes Apex déclarés en config, amorcés au démarrage.

Azraël et KingsRequin n'ont pas à se déclarer à Wally : on connaît leurs
comptes. On les inscrit donc au boot, sur leurs DEUX identités — le vocal les
reconnaît en Discord, le chat en Twitch.
"""
import pytest
import pytest_asyncio

from bot.core.apex.seed import seed_known_accounts
from bot.db.database import Database

REQUESTERS = [
    {"discord_id": "610550333042589752", "twitch_id": "105904256",
     "twitch_login": "kingsrequin", "apex_name": "KingsRequin", "apex_uid": "1012242925358"},
    {"discord_id": "419172225451556874", "twitch_id": "659251746",
     "twitch_login": "azrael_ttv", "apex_name": "Azrael_ttv", "apex_uid": "2274044345"},
]


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest.mark.asyncio
async def test_les_deux_identites_sont_inscrites(db):
    """Le vocal l'identifie en Discord, le chat en Twitch : il faut les deux."""
    await seed_known_accounts(db, REQUESTERS)

    par_discord = await db.apex_get_account("discord:419172225451556874")
    par_twitch = await db.apex_get_account("twitch:659251746")
    assert par_discord["apex_name"] == "Azrael_ttv"
    assert par_twitch["apex_name"] == "Azrael_ttv"
    assert par_discord["uid"] == "2274044345"


@pytest.mark.asyncio
async def test_le_pseudo_de_plateforme_reste_cherchable(db):
    await seed_known_accounts(db, REQUESTERS)
    assert (await db.apex_find_by_display_name("kingsrequin"))["uid"] == "1012242925358"


@pytest.mark.asyncio
async def test_une_declaration_faite_en_direct_n_est_pas_ecrasee(db):
    """Sinon chaque redémarrage annulerait ce que la personne vient de dire."""
    await db.apex_link_account(
        identity="discord:419172225451556874", display_name="azra",
        apex_name="SonNouveauPseudo", apex_platform="PS4", uid="42",
    )

    await seed_known_accounts(db, REQUESTERS)

    compte = await db.apex_get_account("discord:419172225451556874")
    assert compte["apex_name"] == "SonNouveauPseudo"
    assert compte["apex_platform"] == "PS4"


@pytest.mark.asyncio
async def test_une_entree_incomplete_est_ignoree(db):
    """Sans pseudo Apex, il n'y a rien à inscrire — et surtout rien à deviner."""
    await seed_known_accounts(db, [{"discord_id": "1", "twitch_login": "x"}])
    assert await db.apex_get_account("discord:1") is None


@pytest.mark.asyncio
async def test_sans_configuration_rien_ne_se_passe(db):
    await seed_known_accounts(db, [])
    assert await db.apex_find_by_display_name("kingsrequin") is None


# ── la recherche par uid ─────────────────────────────────────────────────────


class _FakeClient:
    available = True

    def __init__(self):
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append(params or {})
        return {"Error": "peu importe"}


@pytest.mark.asyncio
async def test_l_uid_est_prefere_au_pseudo():
    """Un pseudo se change, un uid non — et l'API accepte les deux."""
    from bot.core.apex.service import ApexLegendsService

    client = _FakeClient()
    await ApexLegendsService(client=client).fetch_profile("Azrael_ttv", uid="2274044345")
    assert client.calls[0].get("uid") == "2274044345"
    assert "player" not in client.calls[0]


@pytest.mark.asyncio
async def test_sans_uid_on_cherche_par_pseudo():
    from bot.core.apex.service import ApexLegendsService

    client = _FakeClient()
    await ApexLegendsService(client=client).fetch_profile("Azrael_ttv")
    assert client.calls[0].get("player") == "Azrael_ttv"


@pytest.mark.asyncio
async def test_sans_rien_aucun_appel_reseau():
    from bot.core.apex.service import ApexLegendsService

    client = _FakeClient()
    assert await ApexLegendsService(client=client).fetch_profile("") is None
    assert client.calls == []
