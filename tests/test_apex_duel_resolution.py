# tests/test_apex_duel_resolution.py
"""Un compte introuvable s'explique, il ne se rembourse pas d'emblée.

La recherche par pseudo de l'API rate des comptes parfaitement réels : refuser
au premier essai punirait le viewer pour un défaut qui n'est pas le sien.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Etat
from bot.core.apex.duel_runner import (TENTATIVES_RESOLUTION, URL_APEX_STATUS,
                                       DuelRunner)

PROFIL_OK = {"total": {"k": {"name": "BR Kills", "value": 10}}}


def _runner(profils):
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(profils))
    db = MagicMock(); db.get_state = AsyncMock(return_value=None); db.set_state = AsyncMock()
    api = MagicMock(); api.refund_redemption = AsyncMock(return_value=True)
    annoncer = AsyncMock()
    r = DuelRunner(client=client, db=db, api=api,
                   annoncer=annoncer, azrael_uid="7", plateforme="PC")
    return r, api, annoncer


@pytest.mark.asyncio
async def test_saisie_illisible_demande_l_uid_sans_rembourser():
    runner, api, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    evt = annoncer.await_args.args[0]
    assert evt.type == "compte_introuvable"


@pytest.mark.asyncio
async def test_le_message_porte_l_url_ET_l_astuce_deep_search():
    """L'URL est collée en dur, jamais laissée au LLM : un modèle qui
    reformule une adresse la casse, et un lien mort bloque tout duel."""
    runner, _, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    evt = annoncer.await_args.args[0]
    assert URL_APEX_STATUS in evt.donnees["url"]
    assert "deep search" in evt.donnees["etapes"].lower()


@pytest.mark.asyncio
async def test_une_reponse_correcte_lance_le_duel():
    runner, api, _ = _runner([PROFIL_OK])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    consomme = await runner.repondre_resolution("bob", "1012242925358")
    assert consomme is True
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert runner.duel_en_cours.viewer_uid == "1012242925358"
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_reponse_d_un_AUTRE_viewer_est_ignoree():
    runner, _, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    assert await runner.repondre_resolution("carol", "1012242925358") is False
    assert runner.duel_en_cours.etat is Etat.RESOLUTION


@pytest.mark.asyncio
async def test_apres_N_tentatives_on_rembourse():
    runner, api, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    for _ in range(TENTATIVES_RESOLUTION):
        await runner.repondre_resolution("bob", "toujours pas un uid")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_hors_resolution_le_chat_n_est_pas_consomme():
    """Pendant une manche, un message du duelliste reste un message normal."""
    runner, _, _ = _runner([PROFIL_OK])
    await runner.ouvrir(acheteur="bob", saisie="1012242925358",
                        reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    assert await runner.repondre_resolution("bob", "gg") is False
