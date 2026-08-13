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
    d'envoyer n'importe quelle saisie de viewer à l'API. Un refus qui ne
    rembourse ni n'annonce est le pire résultat possible — et c'est le
    chemin le plus probable en prod (un viewer colle son pseudo)."""
    runner, client, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="'; DROP TABLE--",
                        reward_id="rw", redemption_id="rd")
    client.get.assert_not_awaited()
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    evt = runner._annoncer.await_args.args[0]
    assert evt.type == "refus"


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
async def test_ouvrir_refuse_si_lapi_rend_une_chaine_derreur():
    """`ApexClient.get` rend une CHAÎNE (pas un dict) en cas de panne réseau —
    distinct du corps `{"Error": …}` renvoyé en 200 (cf. test dédié plus bas).
    Cette branche n'était jamais exercée."""
    runner, client, _, api = _runner()
    client.get = AsyncMock(return_value="Apex API error: HTTP 500")
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_ouverture_reussie_persiste_l_etat():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, client, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD
    db.set_state.assert_awaited()
    cle, valeur = db.set_state.await_args.args[:2]
    assert cle == CLE_ETAT
    persiste = json.loads(valeur)
    assert persiste["viewer_uid"] == "42"
    assert persiste["reward_id"] == "rw"
    api.refund_redemption.assert_not_awaited()
    # Exigence explicite (Task 1) : le duel sonde à 2 s, sous le TTL de 15 s
    # de `bridge` — sans `sans_cache=True`, il servirait un relevé périmé
    # sur huit.
    assert client.get.await_args.kwargs.get("sans_cache") is True


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
async def test_charger_restaure_le_reward_id_pour_pouvoir_rembourser():
    """Sans persister le reward_id AVEC le duel, un remboursement après
    rebuild dépend de la chance qu'`assurer_recompense()` retombe sur le même
    ID au redémarrage — sinon `refund_redemption("", …)` échoue, sans annonce
    ni retry."""
    runner, _, db, api = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7", redemption_id="rd")
    duel.etat = Etat.ATTENTE_SQUAD
    etat = duel.to_dict()
    etat["reward_id"] = "RW-PERSISTE"
    db.get_state = AsyncMock(return_value=json.dumps(etat))

    await runner.charger()
    await runner.annuler("le streamer a annulé")

    api.refund_redemption.assert_awaited_once_with("RW-PERSISTE", "rd")


@pytest.mark.asyncio
async def test_annuler_rembourse_et_efface():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.reset_mock()
    db.set_state.reset_mock()
    await runner.annuler("le streamer a annulé")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None
    # « Efface » veut dire en BASE aussi : sans ça, le prochain boot
    # (`charger()`) ressuscite un duel déjà remboursé.
    db.set_state.assert_awaited_with(CLE_ETAT, "")


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


# -- CRITICAL 1/2 : remboursement/nettoyage/persistance AVANT l'annonce -----
# `_annoncer` finit sur un appel LLM puis un envoi Twitch — donc SUR le
# réseau, donc capable de lever. Si elle passait avant le remboursement, une
# exception y perdrait les points du viewer ; si elle passait avant le
# nettoyage et `_ranger()` dans tick(), elle laisserait en prime un duel
# fantôme (mémoire ET base) qui refuserait tous les viewers suivants pour
# toujours, et qu'un rebuild ressusciterait via `charger()`.
@pytest.mark.asyncio
async def test_refuser_rembourse_meme_si_lannonce_leve():
    runner, _, _, api = _runner()
    runner._annoncer = AsyncMock(side_effect=RuntimeError("LLM indisponible"))
    await runner.ouvrir(acheteur="bob", saisie="7", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once_with("rw", "rd")


@pytest.mark.asyncio
async def test_une_annonce_qui_leve_nempeche_ni_remboursement_ni_nettoyage_ni_persistance():
    runner, client, db, api = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.ATTENTE_SQUAD
    duel._t_attente = 0
    runner.duel_en_cours = duel
    client.get = AsyncMock(return_value={"total": {}})
    runner._annoncer = AsyncMock(side_effect=RuntimeError("Twitch indisponible"))

    await runner.tick(maintenant=16 * 60)  # au-delà du délai : timeout -> abandon -> remboursement

    assert runner.duel_en_cours is None, "le duel doit être nettoyé malgré l'annonce ratée"
    api.refund_redemption.assert_awaited_once()
    db.set_state.assert_awaited_with(CLE_ETAT, "")


# -- CRITICAL 3 : un corps {"Error": …} n'est pas un relevé valide ----------
@pytest.mark.asyncio
async def test_profil_rejette_un_corps_error_meme_en_200():
    """Piège documenté du projet : cette API répond aussi 200 avec un corps
    `{"Error": "Player not found."}`. Un `_profil()` qui l'acceptait comme
    relevé valide donnerait `isInGame` absent -> False pour les deux joueurs ;
    deux relevés d'erreur consécutifs suffiraient alors à faire croire à un
    retour au lobby en pleine manche réellement en cours."""
    runner, client, _, api = _runner()
    client.get = AsyncMock(return_value={"Error": "Player not found."})
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"k": 0}
    duel._base_viewer = {"k": 0}
    runner.duel_en_cours = duel

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.MANCHE, "un corps Error ne doit jamais valoir 'hors partie'"
    api.refund_redemption.assert_not_awaited()


# -- IMPORTANT 2 : ne jamais recréer sur un doute ---------------------------
@pytest.mark.asyncio
async def test_assurer_recompense_garde_l_id_connu_si_la_liste_est_indisponible():
    """`recompenses_gerables()` rend `None` sur panne, `[]` seulement sur une
    vraie liste vide (Task 8 fix sur `bot/twitch/api.py`). Recréer sur un
    `None` dupliquerait la récompense et rendrait irremboursable (403) toute
    redemption en vol sur l'ancienne."""
    runner, _, db, api = _runner()
    db.get_state = AsyncMock(return_value="RW-CONNU")
    api.recompenses_gerables = AsyncMock(return_value=None)

    rid = await runner.assurer_recompense("Duel Apex contre Azraël", 5000, "Colle ton UID")

    assert rid == "RW-CONNU"
    api.creer_recompense.assert_not_awaited()
    db.set_state.assert_not_awaited()


# -- IMPORTANT 3 : le minuteur d'attente avance même sans relevé -----------
@pytest.mark.asyncio
async def test_le_minuteur_avance_meme_quand_les_releves_echouent():
    """Une panne d'API pendant ATTENTE_SQUAD ne doit pas geler le duel : sans
    minuteur qui avance, aucun timeout n'est jamais atteint, donc aucun
    remboursement — et `duel_en_cours` resterait peuplé pour toujours,
    refusant tous les viewers suivants."""
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, client, _, api = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.etat is Etat.ATTENTE_SQUAD

    client.get = AsyncMock(return_value="Apex API error: timeout")  # panne : une CHAÎNE
    await runner.tick(maintenant=0)
    await runner.tick(maintenant=16 * 60)

    assert runner.duel_en_cours is None, "le timeout doit être atteint malgré la panne"
    api.refund_redemption.assert_awaited_once()


@pytest.mark.asyncio
async def test_le_minuteur_navance_pas_en_pleine_manche_sur_relevé_échoué():
    """En MANCHE, une panne ne doit PAS injecter de relevé fictif "hors
    partie" : ce serait le même risque que le contrat piégeux #3 mais côté
    entrée, une manche réellement en cours clôturée sur un simple hoquet."""
    runner, client, _, api = _runner()
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"k": 0}
    duel._base_viewer = {"k": 0}
    runner.duel_en_cours = duel
    client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.MANCHE
    api.refund_redemption.assert_not_awaited()


# -- IMPORTANT 4 : `_num` avant `bool`, comme reader.py --------------------
@pytest.mark.asyncio
async def test_isInGame_chaine_0_ne_vaut_pas_en_partie():
    """`bool("0")` vaut `True` en Python nu : cette API glisse parfois des
    chaînes là où on attend un nombre (cf. `reader._num`). Sans cette garde,
    un tel relevé ferait démarrer une manche qui n'a jamais eu lieu."""
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, client, _, _ = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    duel = runner.duel_en_cours
    client.get = AsyncMock(return_value={"realtime": {"isInGame": "0"}, "total": {}})

    # Deux relevés concordants : c'est ce que le debounce d'entrée en manche
    # exige pour confirmer. Avec `bool()` nu, "0" vaudrait True pour les DEUX
    # joueurs (même profil mocké des deux côtés) et les deux confirmations
    # suffiraient à faire basculer le duel en MANCHE.
    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.ATTENTE_SQUAD, "'0' (chaîne) ne doit pas valoir 'en partie'"


# -- IMPORTANT 5 : sans_cache exercé côté sonde également -------------------
@pytest.mark.asyncio
async def test_la_sonde_de_tick_ignore_aussi_le_cache():
    profil = {"total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, client, _, _ = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    duel = runner.duel_en_cours
    duel.etat = Etat.MANCHE
    client.get = AsyncMock(return_value=profil)

    await runner.tick(maintenant=100)

    assert client.get.await_count == 2, "une sonde par joueur (azraël, viewer)"
    for appel in client.get.await_args_list:
        assert appel.kwargs.get("sans_cache") is True


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
    # Même trou côté persistance que « annuler rembourse et efface » : le
    # chemin terminal de tick() doit vider la clé en base, pas seulement la
    # mémoire.
    db.set_state.assert_awaited_with(CLE_ETAT, "")


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
