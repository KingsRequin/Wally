# tests/test_apex_duel_runner.py
"""Le runner : sonde, persistance, remboursements.

La machine à états est testée ailleurs — ici on vérifie le câblage.
"""
import asyncio
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import CLE_ETAT, CLE_RECOMPENSE, DuelRunner, _camp

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _runner(profil_viewer=None, memory=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=profil_viewer or {})
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    api.recompenses_gerables = AsyncMock(return_value=[])
    api.creer_recompense = AsyncMock(return_value="")
    api.maj_recompense = AsyncMock(return_value=True)
    return DuelRunner(client=client, db=db, api=api, memory=memory,
                      annoncer=AsyncMock(), azrael_uid="7", plateforme="PC"), client, db, api


def _lobby(kills: int, en_partie: bool = False) -> dict:
    """Un profil de retour au lobby, avec son compteur de kills."""
    return {"realtime": {"isInGame": 1 if en_partie else 0},
            "total": {"career_kills": {"name": "BR Kills", "value": kills}}}


def _par_uid(profils: dict):
    """Un `client.get` qui répond selon le compte sondé.

    Un compte absent de la table est en PANNE : `ApexClient.get` rend alors une
    chaîne d'erreur, pas un dict.
    """
    async def _get(endpoint, params=None, sans_cache=False):
        return profils.get(str((params or {}).get("uid")), "Apex API error: timeout")
    return AsyncMock(side_effect=_get)


@pytest.mark.asyncio
async def test_uid_non_numerique_demande_l_uid_avant_tout_appel_reseau():
    """Un UID est purement numérique. Le valider AVANT le réseau évite
    d'envoyer n'importe quelle saisie de viewer à l'API. Depuis la Task 8bis,
    une saisie illisible n'est plus remboursée d'emblée : elle ouvre une
    attente de résolution, un silence n'étant jamais acceptable non plus
    (cf. tests/test_apex_duel_resolution.py pour le détail du repli)."""
    runner, client, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="'; DROP TABLE--",
                        reward_id="rw", redemption_id="rd")
    client.get.assert_not_awaited()
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours is not None
    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    evt = runner._annoncer.await_args.args[0]
    assert evt.type == "compte_introuvable"


@pytest.mark.asyncio
async def test_le_compte_d_azrael_est_refuse_et_rembourse():
    runner, _, _, api = _runner()
    await runner.ouvrir(acheteur="bob", saisie="7", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_compte_sans_tracker_de_kills_refuse_et_rembourse():
    """Une clé présente ne prouve pas une valeur vivante, mais une absence
    totale de tracker est éliminatoire d'emblée (§8 de la spec : refus +
    remboursement, avec l'explication).

    Le profil porte bien `realtime` : sans lui, ce test n'exerçait pas la
    branche qu'il annonce mais celle du corps inexploitable."""
    runner, _, _, api = _runner(profil_viewer={
        "realtime": {}, "total": {"d": {"name": "BR Damage", "value": 5}}})
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_une_panne_de_lapi_ne_refuse_pas_un_identifiant_numerique():
    """`ApexClient.get` rend une CHAÎNE (pas un dict) en cas de panne réseau —
    distinct du corps `{"Error": …}` renvoyé en 200 (cf. test dédié plus bas).

    Ce cas était refusé sèchement, remboursé, et annoncé « aucun tracker de
    kills n'est épinglé sur ce compte » : une affirmation fausse sur le compte
    du viewer, prononcée devant le stream pour un hoquet de l'API. Il a droit
    au même traitement qu'un pseudo — l'explication et ses essais."""
    runner, client, _, api = _runner()
    client.get = AsyncMock(return_value="Apex API error: HTTP 500")
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    api.refund_redemption.assert_not_awaited()
    assert runner.duel_en_cours.etat is Etat.RESOLUTION
    evt = runner._annoncer.await_args.args[0]
    assert evt.type == "compte_introuvable"
    assert evt.donnees["cause"] == "api", (
        "la cause annoncée doit être la vraie : l'API, pas son compte")


@pytest.mark.asyncio
async def test_ouverture_reussie_persiste_l_etat():
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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


# -- Un corps vide (ni erreur, ni `realtime`) n'est pas non plus un relevé --
@pytest.mark.asyncio
async def test_profil_rejette_un_corps_sans_realtime():
    """`realtime` est présent dans tous les profils authentiques — y compris
    ceux vérifiés à l'ouverture d'un duel (cf. les deux fixtures réelles
    `bridge_azrael.json` / `bridge_kingsrequin.json`). Un dict SANS clé
    `Error` mais aussi sans `realtime` reproduirait le même piège que le corps
    `{"Error": …}` : `isInGame` absent -> False pour les deux joueurs, et deux
    relevés consécutifs suffiraient à faire croire à un retour au lobby en
    pleine manche réellement en cours."""
    runner, client, _, api = _runner()
    client.get = AsyncMock(return_value={})
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"k": 0}
    duel._base_viewer = {"k": 0}
    runner.duel_en_cours = duel

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.MANCHE, "un corps sans `realtime` ne doit jamais valoir 'hors partie'"
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_ouvrir_n_ouvre_pas_sur_un_profil_sans_realtime():
    """Même garde côté ouverture : un corps vide (200, ni `Error` ni
    `realtime`) ne doit pas suffire à lancer un duel. On n'en conclut rien sur
    le compte pour autant — c'est une réponse inexploitable, pas un compte
    inexistant : le viewer garde ses essais."""
    runner, client, _, api = _runner()
    client.get = AsyncMock(return_value={"total": {"k": {"name": "BR Kills", "value": 10}}})
    await runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.etat is Etat.RESOLUTION, (
        "un corps inexploitable ne lance pas de duel")
    assert runner.duel_en_cours.viewer_uid == ""
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
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
    # Le duelliste menait 5-2, et il n'est pas revenu : un abandon ne rembourse
    # pas, même celui qui mène (cf. tests/test_apex_duel_points.py). La
    # redemption est honorée au lieu de rester en attente.
    api.refund_redemption.assert_not_awaited()
    api.honorer_redemption.assert_awaited_once()
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


# ── Revue finale — CRITICAL 1 : une manche ne se gèle pas pour toujours ──────
# En MANCHE, `tick()` sort sans rien faire quand un relevé manque, et c'est
# délibéré (test ci-dessus). Mais sans contrepartie, une panne prolongée — ou
# un profil devenu illisible — gèle le duel indéfiniment : aucun minuteur ne
# tourne dans cet état, donc jamais de remboursement, et `duel_en_cours` reste
# peuplé, ce qui refuse tous les acheteurs suivants.
def _en_manche(runner):
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7", redemption_id="rd")
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"k": 0}
    duel._base_viewer = {"k": 0}
    runner.duel_en_cours = duel
    runner._reward_id = "rw"
    return duel


@pytest.mark.asyncio
async def test_une_api_muette_trop_longtemps_en_manche_rembourse_et_libere():
    runner, client, db, api = _runner()
    duel = _en_manche(runner)
    client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=1000)          # premier silence
    await runner.tick(maintenant=1000 + 179)    # sous le seuil : on tolère
    assert runner.duel_en_cours is duel, "quelques relevés ratés restent tolérés"
    api.refund_redemption.assert_not_awaited()

    await runner.tick(maintenant=1000 + 181)    # au-delà : plus rien ne viendra

    assert runner.duel_en_cours is None, "le duel doit être libéré, pas gelé"
    api.refund_redemption.assert_awaited_once_with("rw", "rd")
    db.set_state.assert_awaited_with(CLE_ETAT, "")
    evt = runner._annoncer.await_args.args[0]
    assert evt.type == "abandon" and evt.donnees["rembourser"] is True
    assert evt.donnees["motif"], "un abandon muet est aussi mauvais qu'un gel"


@pytest.mark.asyncio
async def test_un_relevé_qui_repasse_efface_le_silence_accumulé():
    """Le seuil porte sur un silence CONTINU. Un trou de deux minutes suivi
    d'un relevé qui passe, puis d'un nouveau trou, ne doit pas s'additionner :
    ce serait abandonner un duel dont l'API répond."""
    profil = {"realtime": {"isInGame": 1}, "total": {"k": {"name": "BR Kills", "value": 3}}}
    runner, client, _, api = _runner()
    duel = _en_manche(runner)
    client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=1000)
    await runner.tick(maintenant=1120)          # 120 s de silence
    client.get = AsyncMock(return_value=profil)
    await runner.tick(maintenant=1130)          # ça repasse
    client.get = AsyncMock(return_value="Apex API error: timeout")
    await runner.tick(maintenant=1140)
    await runner.tick(maintenant=1260)          # 120 s de plus, mais pas 240

    assert runner.duel_en_cours is duel
    assert duel.etat is Etat.MANCHE
    api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_seuil_de_silence_vient_de_la_configuration():
    """Le délai est réglable comme les autres paramètres du duel. Figé dans le
    code, il resterait décoratif dans `config.yaml` — le piège déjà payé sur
    `manches`, `attente_squad_min` et `plafond_kills_manche`."""
    runner, client, _, api = _runner()
    runner._api_muette_max_s = 10.0
    _en_manche(runner)
    client.get = AsyncMock(return_value="Apex API error: timeout")

    await runner.tick(maintenant=500)
    await runner.tick(maintenant=505)
    assert runner.duel_en_cours is not None, "sous le seuil réglé : toléré"
    await runner.tick(maintenant=512)

    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once()


# ── Revue finale — CRITICAL 3 : deux achats à la même seconde ────────────────
@pytest.mark.asyncio
async def test_deux_achats_simultanes_ne_perdent_pas_le_premier():
    """Le test « un duel est-il déjà en cours ? » précède un appel réseau d'une
    seconde environ, et `duel_en_cours` n'était affecté qu'après : deux achats
    rapprochés passaient tous les deux. Le second écrasait le premier, dont le
    `redemption_id` était perdu définitivement — points jamais rendus.

    Le profil rendu ici cède la main (`sleep(0)`) : c'est ce que fait un vrai
    appel réseau, et sans ça les deux coroutines s'exécuteraient bout à bout
    sans jamais s'entrelacer."""
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, client, _, api = _runner()

    async def _lent(*a, **k):
        await asyncio.sleep(0)
        return profil

    client.get = _lent

    await asyncio.gather(
        runner.ouvrir(acheteur="bob", saisie="42", reward_id="rw", redemption_id="rd1"),
        runner.ouvrir(acheteur="carol", saisie="99", reward_id="rw", redemption_id="rd2"),
    )

    assert runner.duel_en_cours is not None
    retenu = runner.duel_en_cours.redemption_id
    perdants = {"rd1", "rd2"} - {retenu}
    # Celui qui n'a pas eu le duel doit avoir récupéré ses points, et l'avoir
    # appris : jamais un remboursement muet, jamais un silence.
    rembourses = {c.args[1] for c in api.refund_redemption.await_args_list}
    assert rembourses == perdants, (
        f"duel retenu : {retenu}, remboursés : {rembourses}")
    types = [c.args[0].type for c in runner._annoncer.await_args_list]
    assert "refus" in types
    assert runner.duel_en_cours.viewer_nom in ("bob", "carol")


# ── Cadence : les deux comptes se sondent EN MÊME TEMPS ─────────────────────
@pytest.mark.asyncio
async def test_les_deux_profils_sont_sondes_en_parallele():
    """Une requête `/bridge` coûte ~1 s de latence, mesurée. Sondés l'un après
    l'autre, les deux comptes coûtent donc ~2 s AVANT le sommeil de cadence :
    la cadence réelle vaut le double de celle annoncée, et le debounce à deux
    relevés porte la détection d'une transition à ~8 s — pour 39 s seulement
    entre un retour au lobby et le lancement suivant. L'API accepte 5 req/s.
    """
    en_vol = 0
    simultanes = 0

    async def _get(endpoint, params=None, sans_cache=False):
        nonlocal en_vol, simultanes
        en_vol += 1
        simultanes = max(simultanes, en_vol)
        await asyncio.sleep(0.01)      # la latence réseau
        en_vol -= 1
        return _lobby(10, en_partie=True)

    runner, client, _, _ = _runner()
    client.get = AsyncMock(side_effect=_get)
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.ATTENTE_SQUAD
    runner.duel_en_cours = duel

    await runner.tick(maintenant=100)

    assert client.get.await_count == 2
    assert simultanes == 2, "les deux comptes doivent être en vol en même temps"


@pytest.mark.asyncio
async def test_un_seul_profil_illisible_abandonne_le_releve_entier():
    """Le garde qui protège des manches closes à tort : si le viewer est
    illisible, on ne clôt pas la manche sur le seul retour au lobby d'Azraël —
    son score à lui serait inventé."""
    runner, client, _, _ = _runner()
    client.get = _par_uid({"7": _lobby(114)})     # le viewer ne répond pas
    duel = Duel(viewer_nom="bob", viewer_uid="42", azrael_uid="7")
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"career_kills": 100}
    duel._base_viewer = {"career_kills": 50}
    runner.duel_en_cours = duel

    await runner.tick(maintenant=100)
    await runner.tick(maintenant=102)

    assert duel.etat is Etat.MANCHE
    assert duel.scores == []


# ── §11 ter : le duel laisse une trace ──────────────────────────────────────
def _duel_sur_le_fil(runner, viewer_id="105904256"):
    """Un duel d'une manche, en cours, prêt à se clore au prochain lobby."""
    runner._client.get = _par_uid({"7": _lobby(111), "42": _lobby(53)})
    duel = Duel(viewer_nom="Bob", viewer_uid="42", viewer_id=viewer_id,
                azrael_uid="7", manches=1)
    duel.etat = Etat.MANCHE
    duel._base_azrael = {"career_kills": 100}
    duel._base_viewer = {"career_kills": 50}
    runner.duel_en_cours = duel
    return duel


async def _clore(runner):
    # Deux relevés pour confirmer le retour au lobby, puis la marge laissée aux
    # compteurs (`marge_lobby_s`, 10 s par défaut) avant que le score ne soit figé.
    for t in (100, 102, 112):
        await runner.tick(maintenant=t)


@pytest.mark.asyncio
async def test_le_resultat_du_duel_part_en_memoire():
    """« tu m'avais mis 11–6 le mois dernier » : une revanche a besoin d'un
    précédent. Le fait doit se lire tel quel — par un humain comme par le
    journal quotidien, qui lit déjà la mémoire."""
    memory = MagicMock()
    memory.add = AsyncMock()
    runner, _, _, _ = _runner(memory=memory)
    _duel_sur_le_fil(runner)

    await _clore(runner)

    memory.add.assert_awaited_once()
    args = memory.add.await_args.args
    assert args[0] == "twitch"
    assert args[1] == "105904256", "l'id BRUT, jamais la forme préfixée"
    fait = args[2]
    assert "Bob" in fait and "Azraël" in fait, f"les deux joueurs : {fait!r}"
    assert "11" in fait and "3" in fait, f"le score final : {fait!r}"
    assert "points de chaîne" in fait, f"l'origine du duel : {fait!r}"


@pytest.mark.asyncio
async def test_une_memoire_en_panne_ne_fait_pas_echouer_le_duel():
    """Le verdict est déjà rendu et les points déjà arbitrés : une trace ratée
    ne doit rien emporter avec elle."""
    memory = MagicMock()
    memory.add = AsyncMock(side_effect=RuntimeError("base morte"))
    runner, _, _, _ = _runner(memory=memory)
    _duel_sur_le_fil(runner)

    await _clore(runner)

    assert runner.duel_en_cours is None
    types = [c.args[0].type for c in runner._annoncer.await_args_list]
    assert "verdict" in types


@pytest.mark.asyncio
async def test_sans_identifiant_twitch_rien_n_est_ecrit_en_memoire():
    """Sans id, il n'y a pas de fiche où ranger ça : deviner par le pseudo
    fabriquerait un utilisateur fantôme que personne ne retrouverait."""
    memory = MagicMock()
    memory.add = AsyncMock()
    runner, _, _, _ = _runner(memory=memory)
    _duel_sur_le_fil(runner, viewer_id="")

    await _clore(runner)

    memory.add.assert_not_awaited()
    assert runner.duel_en_cours is None, "le duel se termine quand même"


@pytest.mark.asyncio
async def test_un_identifiant_de_duelliste_fantaisiste_n_est_pas_retenu():
    """Un id Twitch est purement numérique. Tout le reste est écarté avant
    d'atteindre la mémoire."""
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, _, _ = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="bob", acheteur_id="bob", saisie="42",
                        reward_id="rw", redemption_id="rd")
    assert runner.duel_en_cours.viewer_id == ""


@pytest.mark.asyncio
async def test_l_identifiant_du_duelliste_survit_a_un_rebuild():
    """L'état persisté doit le porter : un duel repris après rebuild se termine
    normalement, et sa trace ne doit pas s'être perdue en route."""
    profil = {"realtime": {}, "total": {"k": {"name": "BR Kills", "value": 10}}}
    runner, _, db, _ = _runner(profil_viewer=profil)
    await runner.ouvrir(acheteur="Bob", acheteur_id="105904256", saisie="42",
                        reward_id="rw", redemption_id="rd")
    ecrit = db.set_state.await_args_list[-1].args[1]

    repris, _, _, _ = _runner()
    repris._db.get_state = AsyncMock(return_value=ecrit)
    await repris.charger()

    assert repris.duel_en_cours.viewer_id == "105904256"


# ── `_camp()` : légende jouée + niveau, sous le nom de chaque joueur ─────────
# Non couvert directement ailleurs — seulement de façon indirecte via `tick()`.
# Un renommage de clé côté API (`selectedLegend`, `global.level`) viderait les
# sous-titres du widget en silence sans qu'aucun test ne le voie.
@pytest.mark.parametrize("nom_fixture", ["bridge_azrael.json", "bridge_kingsrequin.json"])
def test_camp_lit_legende_et_niveau_sur_des_payloads_reels(nom_fixture):
    """Payloads RÉELS versionnés dans les fixtures, pour deux comptes
    distincts — pas une forme reconstruite à la main."""
    profil = json.loads((FIXTURES / nom_fixture).read_text(encoding="utf-8"))

    camp = _camp(profil)

    assert camp["legende"] == profil["realtime"]["selectedLegend"]
    assert camp["niveau"] == profil["global"]["level"]


def test_camp_omet_les_cles_absentes_sur_un_profil_vide():
    """Un sous-titre qui s'écourte, jamais un « niv. 0 » inventé."""
    assert _camp({}) == {}


def test_camp_ne_casse_pas_sur_none():
    assert _camp(None) == {}
