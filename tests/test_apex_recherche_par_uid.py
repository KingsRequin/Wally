"""L'API rate des comptes bien réels quand on la cherche par pseudo.

Signalé le 2026-08-10 : Wally ne trouvait pas `IBrainroTI67`. Vérification faite
directement contre l'API, avec notre clé :

    /bridge?player=IBrainroTI67&platform=PC   → "Player not found. Alternatively,
        we may have encountered an issue while connecting to low priority
        search service."
    idem sur PS4 et X1, idem pour toutes les variantes I/l/1 du pseudo,
    idem depuis le site officiel d'après le propriétaire.

    /bridge?uid=1002761549602                 → trouvé, niveau 48, nom officiel
        « IBrainroTI67 » — exactement le pseudo cherché.

Le compte existe donc, avec ce pseudo précis : c'est la recherche par NOM qui ne
l'indexe pas. Wally n'avait aucun recours — l'outil n'acceptait pas d'uid, et le
message d'échec (« pas trouvé sur l'API Apex ») se lisait comme « ce joueur
n'existe pas ». Personne ne pouvait deviner qu'il fallait donner un uid.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.service import ApexLegendsService, _uid_valide


def _service(reponse):
    s = ApexLegendsService.__new__(ApexLegendsService)
    s._client = MagicMock()
    s._client.get = AsyncMock(return_value=reponse)
    s._db = None
    return s


_PROFIL = {
    "global": {"name": "IBrainroTI67", "uid": "1002761549602",
               "platform": "PC", "level": 48},
    "total": {"kills": {"name": "BR Kills", "value": 120}},
}


def test_un_uid_est_numerique_et_rien_dautre():
    """Le modèle confond volontiers « uid » et « pseudo ». On écarte ici plutôt
    que d'envoyer n'importe quoi à l'API."""
    assert _uid_valide("1002761549602") == "1002761549602"
    assert _uid_valide("  1002761549602 ") == "1002761549602"
    assert _uid_valide("IBrainroTI67") == ""
    assert _uid_valide("12a3") == ""
    assert _uid_valide(None) == ""


@pytest.mark.asyncio
async def test_luid_fourni_sert_a_interroger_lapi():
    service = _service(_PROFIL)

    texte = await service.execute("player_stats", uid="1002761549602")

    assert "IBrainroTI67" in texte
    params = service._client.get.await_args.args[1]
    assert params["uid"] == "1002761549602"
    assert "player" not in params, "l'uid doit remplacer la recherche par pseudo"


@pytest.mark.asyncio
async def test_un_uid_invalide_ne_part_pas_a_lapi():
    """« uid=IBrainroTI67 » doit retomber sur la recherche par pseudo, pas
    produire une requête absurde."""
    service = _service(_PROFIL)

    await service.execute("player_stats", "IBrainroTI67", uid="pas-un-uid")

    params = service._client.get.await_args.args[1]
    assert params.get("player") == "IBrainroTI67"
    assert "uid" not in params


@pytest.mark.asyncio
async def test_lechec_par_pseudo_explique_quoi_faire():
    """« pas trouvé » se lisait comme « ce joueur n'existe pas »."""
    service = _service({"Error": "Player not found."})

    texte = await service.execute("player_stats", "IBrainroTI67")

    assert "introuvable par pseudo" in texte
    assert "uid" in texte, "il faut dire par quoi s'en sortir"
    assert "apexlegendsstatus.com" in texte, "et où le trouver"
    assert "pas forcément une faute de frappe" in texte


@pytest.mark.asyncio
async def test_lechec_par_uid_ne_conseille_pas_luid():
    """Répondre « donne-moi ton uid » à qui vient d'en donner un serait absurde."""
    service = _service({"Error": "Player not found."})

    texte = await service.execute("player_stats", uid="9999999999")

    assert "Vérifie le numéro" in texte
    assert "apexlegendsstatus.com" not in texte


@pytest.mark.asyncio
async def test_memoriser_par_uid_retient_le_nom_officiel():
    """Une recherche par uid n'a pas de pseudo tapé à mémoriser — et l'API rend
    la casse officielle, pas celle demandée (`Azrael_ttv` → `Azrael_TTV`)."""
    service = _service(_PROFIL)
    service._db = MagicMock()
    service._db.apex_link_account = AsyncMock()
    service._db.apex_get_account = AsyncMock(return_value=None)
    service._db.apex_find_by_display_name = AsyncMock(return_value=None)

    await service.execute(
        "player_stats", uid="1002761549602", remember=True,
        requester="discord:1", requester_name="Brain",
    )

    appel = service._db.apex_link_account.await_args.kwargs
    assert appel["apex_name"] == "IBrainroTI67"
    assert appel["uid"] == "1002761549602"
    assert appel["identity"] == "discord:1", "l'identité vient du handler, pas du modèle"


def test_loutil_expose_luid_et_dit_ou_le_trouver():
    from bot.core.apex.tool import APEX_LEGENDS_TOOL

    fonction = APEX_LEGENDS_TOOL["function"]
    uid = fonction["parameters"]["properties"]["uid"]
    assert "apexlegendsstatus.com" in uid["description"]
    assert "remember=true" in uid["description"], (
        "sans mémorisation, il faudrait redonner l'uid à chaque fois"
    )
