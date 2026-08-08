# tests/test_apex_accounts_service.py
"""Le service se souvient du compte Apex des gens, et ne l'invente pour personne.

Le 2026-08-07, faute de mémoire, Wally a redemandé trois fois son pseudo et sa
plateforme à xeforce_ avant d'abandonner.
"""
import json
import pathlib

import pytest
import pytest_asyncio

from bot.core.apex.service import ApexLegendsService
from bot.db.database import Database

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


class _FakeClient:
    available = True

    def __init__(self, reponse):
        self._reponse = reponse
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        return self._reponse


def _bridge(name):
    return json.loads((FIXTURES / f"bridge_{name}.json").read_text(encoding="utf-8"))


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield base
    finally:
        await base.close()


@pytest.mark.asyncio
async def test_sans_pseudo_le_compte_lie_du_demandeur_est_utilise(db):
    await db.apex_link_account(
        identity="twitch:1", display_name="azra",
        apex_name="Azrael_ttv", apex_platform="PC", uid=None,
    )
    client = _FakeClient(_bridge("azrael"))
    svc = ApexLegendsService(client=client, db=db)

    texte = await svc.execute("player_stats", "", requester="twitch:1", requester_name="azra")

    assert client.calls[0][1]["player"] == "Azrael_ttv"
    assert "Azrael_TTV" in texte


@pytest.mark.asyncio
async def test_un_pseudo_de_plateforme_est_traduit_en_compte_apex(db):
    """« les stats de xeforce » → le compte qu'il avait déclaré, sur sa plateforme."""
    await db.apex_link_account(
        identity="twitch:2", display_name="xeforce_",
        apex_name="IBrainroTI67", apex_platform="PS4", uid=None,
    )
    client = _FakeClient(_bridge("kingsrequin"))
    svc = ApexLegendsService(client=client, db=db)

    await svc.execute("player_stats", "xeforce_")

    assert client.calls[0][1]["player"] == "IBrainroTI67"
    assert client.calls[0][1]["platform"] == "PS4"


@pytest.mark.asyncio
async def test_un_pseudo_inconnu_part_tel_quel(db):
    client = _FakeClient(_bridge("kingsrequin"))
    await ApexLegendsService(client=client, db=db).execute("player_stats", "Daltoosh")
    assert client.calls[0][1]["player"] == "Daltoosh"


@pytest.mark.asyncio
async def test_sans_pseudo_ni_compte_lie_wally_demande(db):
    client = _FakeClient(_bridge("kingsrequin"))
    svc = ApexLegendsService(client=client, db=db)
    texte = await svc.execute("player_stats", "", requester="twitch:inconnu")
    assert client.calls == []
    assert "pseudo" in texte.lower()


@pytest.mark.asyncio
async def test_une_declaration_reussie_est_memorisee(db):
    client = _FakeClient(_bridge("azrael"))
    svc = ApexLegendsService(client=client, db=db)

    await svc.execute(
        "player_stats", "Azrael_ttv", remember=True,
        requester="twitch:1", requester_name="azra",
    )

    compte = await db.apex_get_account("twitch:1")
    assert compte["apex_name"] == "Azrael_ttv"
    assert compte["display_name"] == "azra"
    assert compte["uid"] == "2274044345"


@pytest.mark.asyncio
async def test_un_pseudo_introuvable_n_est_jamais_memorise(db):
    """On n'enregistre pas une liaison qui ne mène à rien."""
    client = _FakeClient({"Error": "Player not found"})
    svc = ApexLegendsService(client=client, db=db)

    await svc.execute(
        "player_stats", "NexistePas", remember=True,
        requester="twitch:1", requester_name="azra",
    )

    assert await db.apex_get_account("twitch:1") is None


@pytest.mark.asyncio
async def test_on_ne_peut_pas_declarer_le_compte_d_un_autre(db):
    """La liaison est écrite pour le DEMANDEUR, jamais pour le pseudo cité.

    C'est structurel : le modèle ne fournit pas l'identité, le handler si."""
    client = _FakeClient(_bridge("azrael"))
    svc = ApexLegendsService(client=client, db=db)

    await svc.execute(
        "player_stats", "Azrael_ttv", remember=True,
        requester="twitch:99", requester_name="unTiers",
    )

    assert await db.apex_get_account("twitch:99") is not None
    assert await db.apex_find_by_display_name("Azrael_ttv") is None


@pytest.mark.asyncio
async def test_sans_base_le_service_marche_comme_avant(db):
    """La base est facultative : sans elle, aucune résolution, aucun plantage."""
    client = _FakeClient(_bridge("kingsrequin"))
    svc = ApexLegendsService(client=client)
    texte = await svc.execute("player_stats", "KingsRequin", remember=True, requester="twitch:1")
    assert "KingsRequin" in texte
