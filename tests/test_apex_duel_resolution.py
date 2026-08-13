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


# ── Le silence du duelliste ne gèle plus la fonctionnalité ────────────────────

@pytest.mark.asyncio
async def test_un_duelliste_qui_se_tait_finit_par_etre_rembourse():
    """Le seul défaut capable de geler le duel en silence.

    Une saisie illisible puis plus un mot laissait le duel peuplé pour
    toujours — état persisté, donc rejoué à chaque redémarrage : points jamais
    rendus, et tout acheteur suivant refusé « un duel est déjà en cours ».
    """
    runner, api, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo",
                        reward_id="rw", redemption_id="rd")
    attente = runner.duel_en_cours.attente_squad_s

    await runner.tick(1_000.0)                      # le minuteur démarre
    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()

    await runner.tick(1_000.0 + attente + 1)

    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_attendre_un_uid_ne_coute_aucune_requete():
    """Aucun compte à sonder tant qu'on n'a pas d'uid : rien ne part au réseau."""
    runner, _, _ = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo",
                        reward_id="rw", redemption_id="rd")
    runner._client.get.reset_mock()

    await runner.tick(1_000.0)
    await runner.tick(1_030.0)

    runner._client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_duel_qui_expire_pendant_l_appel_reseau_n_est_pas_ressuscite():
    """La sonde de fond (`tick()`) peut faire expirer le duel PENDANT
    l'appel réseau `_profil()` d'`repondre_resolution()` (~1 s de latence) :
    remboursement, `duel_en_cours = None`, abandon déjà annoncé. Sans garde,
    `repondre_resolution()` reprend sur l'objet orphelin, appelle
    `demarrer_attente_squad()` et annonce un second « duel_ouvert » — le
    viewer lit « ton duel démarre » juste après « ton duel est abandonné »."""
    runner, api, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo",
                        reward_id="rw", redemption_id="rd")
    attente = runner.duel_en_cours.attente_squad_s
    await runner.tick(1_000.0)                      # démarre le minuteur de résolution
    annoncer.reset_mock()

    async def profil_pendant_lequel_le_duel_expire(*args, **kwargs):
        # Simule la boucle de sonde qui tourne PENDANT l'appel réseau et
        # solde le duel (timeout de résolution) avant que la réponse arrive.
        await runner.tick(1_000.0 + attente + 1)
        return PROFIL_OK

    runner._client.get = AsyncMock(side_effect=profil_pendant_lequel_le_duel_expire)

    consomme = await runner.repondre_resolution("bob", "1012242925358")

    assert consomme is True
    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once()
    assert annoncer.await_count == 1
    assert annoncer.await_args.args[0].type == "abandon"


@pytest.mark.asyncio
async def test_le_duel_qui_expire_pendant_le_dernier_essai_ne_rembourse_pas_deux_fois():
    """Symétrique : la 3e tentative échouée peut aussi croiser un duel qui
    vient d'expirer pendant l'appel réseau. Sans garde, `repondre_resolution()`
    rembourse une seconde fois la même redemption (refusée par Twitch) et
    annonce un second abandon."""
    runner, api, annoncer = _runner([])
    await runner.ouvrir(acheteur="bob", saisie="mon pseudo",
                        reward_id="rw", redemption_id="rd")
    attente = runner.duel_en_cours.attente_squad_s
    await runner.tick(1_000.0)                      # démarre le minuteur de résolution

    # Deux échecs de saisie, pour amener le compteur juste avant le seuil.
    await runner.repondre_resolution("bob", "toujours pas un uid")
    await runner.repondre_resolution("bob", "toujours pas un uid")
    annoncer.reset_mock()

    async def profil_pendant_lequel_le_duel_expire(*args, **kwargs):
        await runner.tick(1_000.0 + attente + 1)
        return None  # compte introuvable : la sonde a de toute façon déjà tranché

    runner._client.get = AsyncMock(side_effect=profil_pendant_lequel_le_duel_expire)

    consomme = await runner.repondre_resolution("bob", "1012242925358")

    assert consomme is True
    api.refund_redemption.assert_awaited_once()
    assert annoncer.await_count == 1
    assert annoncer.await_args.args[0].type == "abandon"


@pytest.mark.asyncio
async def test_le_compte_donne_a_temps_rouvre_un_delai_entier():
    """Le délai d'attente du squad repart à neuf, il n'hérite pas de la
    résolution — sinon un viewer lent serait abandonné avant d'avoir joué."""
    # Assez de profils pour les relevés qui suivront la reprise du duel.
    runner, api, _ = _runner([PROFIL_OK] * 5)
    await runner.ouvrir(acheteur="bob", saisie="x", reward_id="rw", redemption_id="rd")
    attente = runner.duel_en_cours.attente_squad_s
    await runner.tick(1_000.0)                      # minuteur de résolution

    await runner.repondre_resolution("bob", "1012242925358")
    # Passé le délai compté DEPUIS la résolution : avec un minuteur hérité, le
    # duel serait abandonné ici alors que le squad vient tout juste d'être formé.
    await runner.tick(1_000.0 + attente + 1)

    assert runner.duel_en_cours is not None
    api.refund_redemption.assert_not_awaited()
