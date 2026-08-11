# tests/test_apex_resolution_pseudo.py
"""Retrouver le compte Apex de quelqu'un depuis le nom qu'on lâche en passant.

Constaté en prod le 2026-08-11 : « wally donne la courbe de kills de azra
d'aujourd'hui » → « j'ai pas de relevés pour aujourd'hui ». Les relevés
existaient pourtant. La recherche de compte exigeait le pseudo EXACT
(`azrael_ttv`), donc ni « azra » ni « Azraël » ne trouvaient quoi que ce soit,
et la question partait interroger l'API sur un pseudo inconnu.

Personne n'écrit le pseudo de plateforme complet dans une phrase.
"""
import pytest
import pytest_asyncio

from bot.core.apex.service import ApexLegendsService
from bot.db.database import Database

UID_AZRAEL = "2274044345"
UID_REQUIN = "1012242925358"


@pytest_asyncio.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    await base.apex_link_account(
        identity="discord:419172225451556874", display_name="azrael_ttv",
        apex_name="Azrael_ttv", apex_platform="PC", uid=UID_AZRAEL,
    )
    await base.apex_link_account(
        identity="discord:610550333042589752", display_name="kingsrequin",
        apex_name="KingsRequin", apex_platform="PC", uid=UID_REQUIN,
    )
    try:
        yield base
    finally:
        await base.close()


@pytest_asyncio.fixture
async def service(db):
    return ApexLegendsService(client=object(), db=db)


@pytest.mark.parametrize("ecrit", ["azrael_ttv", "Azrael_ttv", "AZRAEL_TTV"])
@pytest.mark.asyncio
async def test_le_pseudo_exact_marche_toujours(service, ecrit):
    assert await service._resolve_uid(None, ecrit) == UID_AZRAEL


@pytest.mark.parametrize("ecrit", ["azra", "Azraël", "azrael", "Azrael"])
@pytest.mark.asyncio
async def test_le_surnom_courant_retrouve_le_compte(service, ecrit):
    """Ce que les gens écrivent vraiment dans une phrase."""
    assert await service._resolve_uid(None, ecrit) == UID_AZRAEL


@pytest.mark.parametrize("ecrit", ["requin", "KingsRequin", "kings"])
@pytest.mark.asyncio
async def test_le_surnom_marche_pour_les_autres_aussi(service, ecrit):
    assert await service._resolve_uid(None, ecrit) == UID_REQUIN


@pytest.mark.asyncio
async def test_un_inconnu_reste_inconnu(service):
    """Le repli flou ne doit pas attribuer n'importe qui au premier venu."""
    assert await service._resolve_uid(None, "Daltoosh") is None
    assert await service._resolve_uid(None, "zzzz") is None


@pytest.mark.asyncio
async def test_deux_lettres_ne_designent_personne(service):
    """En deçà de trois caractères, une sous-chaîne rapproche n'importe qui."""
    assert await service._resolve_uid(None, "az") is None


@pytest.mark.asyncio
async def test_sans_nom_on_prend_le_compte_du_demandeur(service):
    uid = await service._resolve_uid("discord:419172225451556874", "")
    assert uid == UID_AZRAEL


@pytest.mark.asyncio
async def test_le_pseudo_l_emporte_sur_le_demandeur(service):
    """« les kills d'azra » demandé par KingsRequin parle bien d'Azraël."""
    uid = await service._resolve_uid("discord:610550333042589752", "azra")
    assert uid == UID_AZRAEL
