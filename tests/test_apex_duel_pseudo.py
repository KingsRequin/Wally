# tests/test_apex_duel_pseudo.py
"""Le duelliste peut donner son PSEUDO, pas seulement son identifiant.

La spec le prévoyait (§3) ; l'implémentation avait réduit le périmètre à une
saisie purement numérique, et tout le reste partait au mode d'emploi. Un achat
qui coûte des points ne devrait pas commencer par une chasse à l'UID.

Ce qui ne change pas : le repli reste indispensable. La recherche par pseudo de
cette API rate des comptes parfaitement réels — mesuré sur plusieurs comptes, y
compris avec la casse officielle.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Etat
from bot.core.apex.duel_runner import URL_APEX_STATUS, DuelRunner

UID_VIEWER = "1012242925358"

PROFIL_VIEWER = {
    "global": {"uid": UID_VIEWER, "name": "Le Duelliste"},
    "realtime": {"isInGame": 0},
    "total": {"career_kills": {"name": "BR Kills", "value": 10}},
}

# Le compte du streamer, tel que l'API le rend quand on le cherche par pseudo.
PROFIL_AZRAEL = {
    "global": {"uid": "7", "name": "Azrael"},
    "realtime": {"isInGame": 0},
    "total": {"career_kills": {"name": "BR Kills", "value": 18782}},
}

INTROUVABLE = {"Error": "Player not found."}


def _runner(reponse=INTROUVABLE):
    client = MagicMock()
    client.get = AsyncMock(return_value=reponse)
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    annoncer = AsyncMock()
    runner = DuelRunner(client=client, db=db, api=api, annoncer=annoncer,
                        azrael_uid="7", plateforme="PC")
    return runner, client, api, annoncer


def _types(annoncer) -> list[str]:
    return [c.args[0].type for c in annoncer.await_args_list]


@pytest.mark.asyncio
async def test_un_pseudo_ouvre_le_duel_comme_un_identifiant():
    runner, _, api, _ = _runner(PROFIL_VIEWER)

    await runner.ouvrir(acheteur="bob", saisie="Le Duelliste",
                        reward_id="rw", redemption_id="rd")

    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert runner.duel_en_cours.viewer_uid == UID_VIEWER, (
        "c'est l'identifiant résolu qui doit être sondé ensuite, pas le pseudo")
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_pseudo_voyage_intact_et_avec_sa_plateforme():
    """L'API veut la plateforme dans les deux cas, et le pseudo doit lui
    arriver tel qu'il a été saisi — accents et espaces compris. Le passer en
    paramètre est ce qui l'échappe ; le coller dans une URL casserait le
    premier pseudo venu."""
    runner, client, _, _ = _runner(PROFIL_VIEWER)

    await runner.ouvrir(acheteur="bob", saisie="Rêveur [FR]",
                        reward_id="rw", redemption_id="rd")

    # La recherche par pseudo parmi les appels du tour : l'ouverture en fait
    # d'autres (le compte d'Azraël est sondé avant de lancer le duel), et
    # prendre « le dernier appel » les confondrait.
    params = [c.args[1] for c in client.get.await_args_list
              if "player" in (c.args[1] or {})]
    assert params, "la recherche par pseudo n'a pas eu lieu"
    assert params[0]["player"] == "Rêveur [FR]"
    assert params[0]["platform"] == "PC"


@pytest.mark.asyncio
async def test_un_pseudo_introuvable_retombe_sur_le_mode_d_emploi():
    """L'index de l'API rate des comptes réels : on explique, on ne refuse
    pas, et surtout on ne rembourse pas d'emblée."""
    runner, _, api, annoncer = _runner(INTROUVABLE)

    await runner.ouvrir(acheteur="bob", saisie="CompteBienReel",
                        reward_id="rw", redemption_id="rd")

    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    evt = annoncer.await_args.args[0]
    assert evt.type == "compte_introuvable"
    assert URL_APEX_STATUS in evt.donnees["url"]
    assert "deep search" in evt.donnees["etapes"].lower()


@pytest.mark.asyncio
async def test_un_profil_sans_identifiant_retombe_aussi_sur_le_mode_d_emploi():
    """Un compte trouvé mais sans uid n'est pas sondable : sans identifiant,
    chaque relevé du duel taperait dans le vide."""
    runner, _, api, annoncer = _runner({"global": {"name": "Fantome"},
                                        "realtime": {},
                                        "total": {"k": {"name": "BR Kills", "value": 3}}})

    await runner.ouvrir(acheteur="bob", saisie="Fantome",
                        reward_id="rw", redemption_id="rd")

    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    assert _types(annoncer) == ["compte_introuvable"]
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("saisie", [
    "'; DROP TABLE--",
    "<script>alert(1)</script>",
    "https://apexlegendsstatus.com/profile/uid/PC/123",
    "a" * 200,
    "ab",
    "",
])
async def test_une_saisie_aberrante_ne_part_jamais_au_reseau(saisie):
    """La saisie vient d'un viewer : rien ne justifie d'envoyer ça à une API
    tierce. Elle est jugée AVANT le réseau, et tombe sur le mode d'emploi."""
    runner, client, api, annoncer = _runner()

    await runner.ouvrir(acheteur="bob", saisie=saisie,
                        reward_id="rw", redemption_id="rd")

    client.get.assert_not_awaited()
    api.refund_redemption.assert_not_awaited()
    assert _types(annoncer) == ["compte_introuvable"]


@pytest.mark.asyncio
async def test_le_PSEUDO_du_streamer_est_refuse_et_rembourse():
    """Un duel contre soi-même n'a pas de vainqueur. La comparaison ne portait
    que sur l'identifiant : donner « Azrael » au lieu de son numéro ouvrait un
    duel du streamer contre lui-même, que rien n'aurait pu départager."""
    runner, _, api, annoncer = _runner(PROFIL_AZRAEL)

    await runner.ouvrir(acheteur="bob", saisie="Azrael",
                        reward_id="rw", redemption_id="rd")

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    assert _types(annoncer) == ["refus"]


@pytest.mark.asyncio
async def test_un_pseudo_donne_APRES_coup_lance_aussi_le_duel():
    """Le viewer qui a raté sa première saisie n'est pas condamné à l'UID :
    il peut corriger son pseudo dans le chat."""
    runner, client, api, _ = _runner(INTROUVABLE)
    await runner.ouvrir(acheteur="bob", saisie="PseudoFaux",
                        reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.etat is Etat.RESOLUTION

    client.get = AsyncMock(return_value=PROFIL_VIEWER)
    consomme = await runner.repondre_resolution("bob", "Le Duelliste")

    assert consomme is True
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert runner.duel_en_cours.viewer_uid == UID_VIEWER
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_pseudo_du_streamer_donne_APRES_coup_ne_lance_rien():
    """Même garde sur le second chemin : il ne suffit pas de le poser à
    l'ouverture."""
    runner, client, _, _ = _runner(INTROUVABLE)
    await runner.ouvrir(acheteur="bob", saisie="PseudoFaux",
                        reward_id="rw", redemption_id="rd")

    client.get = AsyncMock(return_value=PROFIL_AZRAEL)
    await runner.repondre_resolution("bob", "Azrael")

    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    assert runner.duel_en_cours.viewer_uid == ""
