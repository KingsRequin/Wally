# tests/test_apex_duel_runner.py
"""Le runner : sonde, persistance, remboursements.

La machine à états est testée ailleurs — ici on vérifie le câblage.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import CLE_ETAT, CLE_RECOMPENSE, DuelRunner


def _runner(profil_viewer=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=profil_viewer or {})
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.recompenses_gerables = AsyncMock(return_value=[])
    api.creer_recompense = AsyncMock(return_value="")
    return DuelRunner(client=client, db=db, api=api, feed=MagicMock(),
                      annoncer=AsyncMock(), azrael_uid="7", plateforme="PC"), client, db, api


@pytest.mark.asyncio
async def test_uid_non_numerique_refuse_avant_tout_appel_reseau():
    """Un UID est purement numérique. Le valider AVANT le réseau évite
    d'envoyer n'importe quelle saisie de viewer à l'API."""
    runner, client, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="'; DROP TABLE--",
                        reward_id="rw", redemption_id="rd")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_compte_d_azrael_est_refuse_et_rembourse():
    runner, _, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="7", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_compte_sans_tracker_de_kills_refuse_et_rembourse():
    """Une clé présente ne prouve pas une valeur vivante, mais une absence
    totale de tracker est éliminatoire d'emblée."""
    runner, _, _, api = _runner(profil_viewer={"total": {"d": {"name": "BR Damage", "value": 5}}})
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_ouverture_reussie_persiste_l_etat():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    db.set_state.assert_awaited()
    cle, valeur = db.set_state.await_args.args[:2]
    assert cle == CLE_ETAT
    assert json.loads(valeur)["viewer_uid"] == "42"
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_reprise_apres_rebuild():
    runner, _, db, _ = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 3, "viewer": 1}]
    db.get_state = AsyncMock(return_value=json.dumps(duel.to_dict()))
    await runner.charger()
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.scores == [{"azrael": 3, "viewer": 1}]


@pytest.mark.asyncio
async def test_etat_corrompu_en_base_ne_casse_pas_le_boot():
    runner, _, db, _ = _runner()
    db.get_state = AsyncMock(return_value="{ pas du json")
    await runner.charger()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_annuler_rembourse_et_efface():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.reset_mock()
    await runner.annuler("le streamer a annulé")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_recommencer_ne_rembourse_PAS():
    """Le viewer garde sa place — les points restent dépensés."""
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, _, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    runner.duel_en_cours.scores = [{"azrael": 2, "viewer": 1}]
    api.refund_redemption.reset_mock()
    await runner.recommencer()
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours.scores == []


# -- tick() : nettoyage sur un état TERMINAL, pas sur ABANDON précisément ----
# Contrat piégeux relevé par la revue de duel.py : après un abandon survenu
# alors qu'au moins une manche a été mesurée, l'état final rendu par
# `avancer()` est VERDICT, pas ABANDON. Un `tick()` qui ne nettoierait que sur
# `etat is Etat.ABANDON` laisserait `duel_en_cours` peuplé pour toujours après
# ce cas précis — le duel resterait « en cours » indéfiniment côté runner.
@pytest.mark.asyncio
async def test_tick_nettoie_meme_quand_labandon_tranche_en_verdict():
    runner, client, db, api = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.ENTRE_MANCHES
    # Une manche déjà mesurée : un abandon depuis cet état ne rembourse pas et
    # tranche sur les manches jouées (etat -> VERDICT, jamais ABANDON).
    duel.scores = [{"azrael": 2, "viewer": 5}]
    duel._t_attente = 0
    runner.duel_en_cours = duel
    client.get = AsyncMock(return_value={"total": {}})

    # t bien au-delà du délai d'attente (15 min par défaut) : timeout confirmé.
    await runner.tick(maintenant=16 * 60)

    assert duel.etat is Etat.VERDICT
    assert runner.duel_en_cours is None, "le duel terminal doit être nettoyé, VERDICT compris"
    api.refund_redemption.assert_not_awaited()
    types_annonces = [c.args[0].type for c in runner._annoncer.await_args_list]
    assert "abandon" in types_annonces
    assert "verdict" in types_annonces


# -- Refus « un duel est déjà en cours » : ANNONCÉ, pas seulement remboursé --
# La Task 7 ne pouvait pas le tenir, faute de canal d'annonce : le runner
# détient `_annoncer`, c'est donc ici que ce chemin se ferme.
@pytest.mark.asyncio
async def test_duel_deja_en_cours_est_refuse_et_annonce_sans_ecraser_le_duel():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, _, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    en_cours = runner.duel_en_cours
    api.refund_redemption.reset_mock()
    runner._annoncer.reset_mock()

    await runner.ouvrir(acheteur="carol", saisie="99", reward_id="rw2", redemption_id="rd2")

    api.refund_redemption.assert_awaited_once_with("rw2", "rd2")
    evt = runner._annoncer.await_args.args[0]
    assert evt.type == "refus"
    assert runner.duel_en_cours is en_cours, "le duel en cours ne doit jamais être écrasé"


# -- assurer_recompense : déplacé ici depuis la Task 7 par ruling du contrôleur --
@pytest.mark.asyncio
async def test_assurer_recompense_reutilise_un_id_connu_et_gerable():
    runner, _, db, api = _runner()
    db.get_state = AsyncMock(return_value="RW1")
    api.recompenses_gerables = AsyncMock(return_value=[{"id": "RW1"}, {"id": "AUTRE"}])

    rid = await runner.assurer_recompense("Duel Apex contre Azraël", 5000, "Colle ton UID")

    assert rid == "RW1"
    api.creer_recompense.assert_not_awaited()
    db.set_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_assurer_recompense_recree_si_id_connu_absent_des_gerables():
    """Récompense supprimée côté Twitch (ou créée à la main dans la console) :
    on en recrée une, sinon les remboursements échoueraient en 403."""
    runner, _, db, api = _runner()
    db.get_state = AsyncMock(return_value="ANCIEN")
    api.recompenses_gerables = AsyncMock(return_value=[{"id": "AUTRE"}])
    api.creer_recompense = AsyncMock(return_value="NOUVEAU")

    rid = await runner.assurer_recompense("Duel Apex contre Azraël", 5000, "Colle ton UID")

    assert rid == "NOUVEAU"
    api.creer_recompense.assert_awaited_once()
    db.set_state.assert_awaited_once_with(CLE_RECOMPENSE, "NOUVEAU")
