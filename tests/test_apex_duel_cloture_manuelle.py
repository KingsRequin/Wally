# tests/test_apex_duel_cloture_manuelle.py
"""« C'est fini, prends les résultats » — la clôture manuelle du duel.

Le duel se découpe en manches sur la détection du retour au lobby d'Azraël.
Rater cette transition — un rebuild au mauvais moment, un hoquet de l'API —
laissait la manche ouverte et le duel en cours indéfiniment, alors que le stream
savait très bien que la partie était finie. La seule sortie était `annuler`, qui
JETTE le résultat de la partie qu'on vient de jouer et rembourse.

Ce qui se vérifie ici : le verdict est rendu sur ce qui a été MESURÉ (dernière
manche comprise), les points suivent la règle ordinaire du duel, une absence de
mesure ne devient jamais un match nul, et l'autorisation se lit sur le badge du
message réel.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.apex.duel import Duel, Etat, Evenement, Releve
from bot.core.apex.duel_runner import CLE_ETAT, DuelRunner
from bot.twitch.duel_announce import _fait
from bot.twitch.handlers import make_tool_executor
from tests.test_twitch_handlers import make_bot

VIEWER_ID = "105904256"
K0 = {"career_kills": 1000}


def kills(n: int) -> dict:
    return {"career_kills": 1000 + n}


def _en_manche(manches: int = 3) -> Duel:
    """Un duel dont la manche 1 est en cours, base de kills posée."""
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7", manches=manches,
             marge_lobby_s=0)
    d.etat = Etat.ATTENTE_SQUAD
    for t in (0, 2):
        d.avancer(Releve(t=t, azrael_in_game=True, viewer_in_game=True,
                         kills_azrael=K0, kills_viewer=K0))
    assert d.etat is Etat.MANCHE, "le duel doit être en manche pour ces tests"
    return d


def _dernier(ka: int, kv: int, t: float = 500) -> Releve:
    """Le relevé pris au moment de la clôture.

    `in_game` reste VRAI des deux côtés : c'est tout le scénario — la partie est
    finie, mais le retour au lobby n'a jamais été vu.
    """
    return Releve(t=t, azrael_in_game=True, viewer_in_game=True,
                  kills_azrael=kills(ka), kills_viewer=kills(kv))


def _verdict(evts: list[Evenement]) -> dict:
    verdicts = [e.donnees for e in evts if e.type == "verdict"]
    assert verdicts, f"aucun verdict rendu : {[e.type for e in evts]}"
    return verdicts[0]


# ── La machine ──────────────────────────────────────────────────────────────
def test_la_manche_en_cours_compte_si_elle_est_mesurable():
    """Le cas d'usage même : la partie est réellement finie, seule la détection
    a échoué. La jeter reviendrait à punir le duelliste d'un défaut de mesure."""
    d = _en_manche()

    v = _verdict(d.clore_a_la_main(_dernier(ka=2, kv=6)))

    assert (v["azrael"], v["viewer"]) == (2, 6)
    assert v["gagnant"] == "viewer"
    assert d.etat is Etat.VERDICT


@pytest.mark.parametrize("ka, kv, gagnant, rembourse", [
    (2, 6, "viewer", True),     # il gagne : sa mise lui revient
    (6, 2, "azrael", False),    # il perd : sa mise est consommée
    (3, 3, None, True),         # égalité : le doute lui profite
])
def test_les_points_suivent_la_regle_ordinaire_du_duel(ka, kv, gagnant, rembourse):
    """Une clôture manuelle n'est PAS un abandon : personne n'a quitté le duel,
    c'est le stream qui tranche. L'anti-abandon — qui prive de remboursement
    même celui qui mène — n'a donc rien à punir ici."""
    d = _en_manche()

    v = _verdict(d.clore_a_la_main(_dernier(ka=ka, kv=kv)))

    assert v["gagnant"] == gagnant
    assert v["rembourser"] is rembourse


def test_sans_rien_de_mesurable_aucun_verdict_et_les_points_reviennent():
    """Une absence de mesure n'est pas un zéro : annoncer « 0-0, match nul » à
    deux joueurs qui viennent de jouer est le mensonge que tout ce module
    refuse. Le duel s'arrête, et les points reviennent."""
    d = _en_manche()

    evts = d.clore_a_la_main(Releve(t=500, azrael_in_game=True, viewer_in_game=True,
                                    kills_azrael={}, kills_viewer={}))

    assert "verdict" not in [e.type for e in evts]
    abandon = next(e for e in evts if e.type == "abandon")
    assert abandon.donnees["rembourser"] is True
    annonce = _fait(abandon, "Bob")
    assert not any(c.isdigit() for c in annonce), (
        f"aucun chiffre à annoncer, rien n'a été compté : {annonce!r}")


def test_une_derniere_manche_illisible_ne_touche_pas_aux_manches_comptees():
    """L'API se tait au moment de la clôture : la manche en cours ne compte pour
    personne, mais celles déjà mesurées restent le verdict."""
    d = _en_manche()
    d.scores = [{"azrael": 4, "viewer": 1, "azrael_lu": 4, "viewer_lu": 1}]

    v = _verdict(d.clore_a_la_main(Releve(
        t=500, azrael_in_game=True, viewer_in_game=True,
        kills_azrael={}, kills_viewer={})))

    assert (v["azrael"], v["viewer"]) == (4, 1)
    assert v["manches_comptees"] == 1, "la manche illisible ne se compte pas"


def test_lannonce_ne_presente_pas_un_duel_clos_a_la_main_comme_un_duel_ordinaire():
    """Un 13–1 sur deux manches n'est pas un 13–1 sur cinq. Le taire ferait
    passer une victoire partielle pour une victoire nette."""
    donnees = {"azrael": 13, "viewer": 1, "gagnant": "azrael", "abandon": False,
               "manuel": True, "manches_comptees": 2, "manches": 5,
               "rembourser": False, "scores": [{"azrael": 13, "viewer": 1}],
               "camps": {}}

    annonce = _fait(Evenement("verdict", donnees), "Bob")

    assert annonce != _fait(Evenement("verdict", {**donnees, "manuel": False}), "Bob")
    assert "2" in annonce, f"le nombre de manches comptées doit être dit : {annonce!r}"
    assert "5" in annonce, f"sur combien de manches prévues : {annonce!r}"


def test_un_duel_deja_solde_ne_se_clot_pas_une_seconde_fois():
    """Deux ordres contradictoires sur la même redemption : le second serait
    perdu, une redemption FULFILLED ne redevient jamais CANCELED."""
    d = _en_manche()
    d.clore_a_la_main(_dernier(ka=3, kv=1))
    assert d.etat is Etat.VERDICT

    assert d.clore_a_la_main(_dernier(ka=9, kv=9, t=600)) == []


def test_un_etat_persiste_par_la_version_en_prod_se_clot_a_la_main():
    """Un duel commencé avant ce correctif, repris après le rebuild : son état
    ne porte ni les clés `*_lu` ni rien de neuf. Il doit se clore quand même."""
    d = Duel.from_dict({
        "viewer_nom": "Bob", "viewer_uid": "42", "azrael_uid": "7",
        "manches": 3, "etat": "manche",
        "scores": [{"azrael": 4, "viewer": 1}],
    })

    v = _verdict(d.clore_a_la_main(_dernier(ka=2, kv=2, t=1)))

    assert (v["azrael"], v["viewer"]) == (4, 1)
    assert v["manches_comptees"] == 1


# ── Le runner ───────────────────────────────────────────────────────────────
def _profil(kills_totaux: int) -> dict:
    return {"realtime": {"isInGame": 1},
            "total": {"career_kills": {"name": "BR Kills", "value": kills_totaux}}}


def _runner(profils: dict | None = None, memory=None):
    client = MagicMock()

    async def _get(_endpoint, params=None, **_kw):
        return (profils or {}).get(str((params or {}).get("uid")),
                                   "Apex API error: timeout")

    client.get = AsyncMock(side_effect=_get)
    db = MagicMock()
    db.get_state = AsyncMock(return_value=None)
    db.set_state = AsyncMock()
    api = MagicMock()
    api.refund_redemption = AsyncMock(return_value=True)
    api.honorer_redemption = AsyncMock(return_value=True)
    runner = DuelRunner(client=client, db=db, api=api, memory=memory,
                        annoncer=AsyncMock(), azrael_uid="7")
    runner._reward_id = "rw"
    duel = Duel(viewer_nom="Bob", viewer_uid="42", viewer_id=VIEWER_ID,
                azrael_uid="7", redemption_id="rd", manches=3, marge_lobby_s=0,
                etat=Etat.MANCHE)
    duel._base_azrael = dict(K0)
    duel._base_viewer = dict(K0)
    runner.duel_en_cours = duel
    return runner, client, api, duel


@pytest.mark.asyncio
async def test_terminer_prend_un_dernier_releve_et_compte_la_manche_en_cours():
    runner, _, api, _ = _runner({"7": _profil(1002), "42": _profil(1006)})

    evt = await runner.terminer()

    assert evt.type == "verdict"
    assert (evt.donnees["azrael"], evt.donnees["viewer"]) == (2, 6)
    assert runner.duel_en_cours is None
    api.refund_redemption.assert_awaited_once_with("rw", "rd")


@pytest.mark.asyncio
async def test_terminer_solde_et_range_meme_si_lannonce_leve():
    """L'ordre remboursement → nettoyage → persistance → annonce. Une annonce
    qui lève (LLM, envoi Twitch) ne doit laisser ni points en suspens ni duel
    fantôme qu'un rebuild ressusciterait."""
    runner, _, api, _ = _runner({"7": _profil(1002), "42": _profil(1006)})
    runner._annoncer = AsyncMock(side_effect=RuntimeError("LLM indisponible"))

    await runner.terminer()

    api.refund_redemption.assert_awaited_once()
    assert runner.duel_en_cours is None
    runner._db.set_state.assert_awaited_with(CLE_ETAT, "")


@pytest.mark.asyncio
async def test_une_api_muette_ne_bloque_pas_la_cloture():
    """Le duel doit pouvoir se fermer même quand plus rien ne se lit — c'est
    justement une des raisons pour lesquelles il s'est coincé."""
    runner, _, _, duel = _runner({})
    duel.scores = [{"azrael": 4, "viewer": 1, "azrael_lu": 4, "viewer_lu": 1}]

    evt = await runner.terminer()

    assert evt.type == "verdict"
    assert (evt.donnees["azrael"], evt.donnees["viewer"]) == (4, 1)
    assert runner.duel_en_cours is None


@pytest.mark.asyncio
async def test_hors_manche_la_cloture_ne_sonde_rien():
    """Entre deux manches il n'y a rien à mesurer, et en résolution pas même
    d'identifiant à interroger : deux requêtes pour rien."""
    runner, client, _, duel = _runner({"7": _profil(1002), "42": _profil(1006)})
    duel.etat = Etat.ENTRE_MANCHES
    duel.scores = [{"azrael": 4, "viewer": 1, "azrael_lu": 4, "viewer_lu": 1}]

    evt = await runner.terminer()

    client.get.assert_not_awaited()
    assert evt.type == "verdict"
    assert (evt.donnees["azrael"], evt.donnees["viewer"]) == (4, 1)


@pytest.mark.asyncio
async def test_la_trace_memoire_dit_que_le_duel_na_pas_ete_mene_a_son_terme():
    """« Tu m'avais mis 6–2 le mois dernier » n'a de valeur que si c'est vrai :
    un duel clos à la main n'est pas un duel gagné de bout en bout."""
    memory = MagicMock()
    memory.add = AsyncMock()
    runner, _, _, _ = _runner({"7": _profil(1002), "42": _profil(1006)},
                              memory=memory)

    await runner.terminer()

    assert memory.add.await_args is not None, "aucune trace écrite"
    fait = memory.add.await_args.args[2]
    bas = fait.lower()
    assert "à la main" in bas or "clos" in bas, (
        f"la trace doit dire que le duel a été arrêté à la main : {fait!r}")
    assert "6" in fait and "Bob" in fait, f"le score compté reste dit : {fait!r}"


@pytest.mark.asyncio
async def test_un_remboursement_refuse_ne_sannonce_pas_comme_un_succes():
    runner, _, api, _ = _runner({"7": _profil(1002), "42": _profil(1006)})
    api.refund_redemption = AsyncMock(return_value=False)

    evt = await runner.terminer()

    assert evt.donnees.get("remboursement_echoue") is True


# ── L'outil du chat ─────────────────────────────────────────────────────────
def _bot_avec_duel(retour=None):
    bot = make_bot(trigger_names=["wally"])
    duel = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7",
                etat=Etat.MANCHE)
    duel.scores = [{"azrael": 4, "viewer": 1}]
    runner = MagicMock()
    runner.duel_en_cours = duel
    runner.terminer = AsyncMock(return_value=retour)
    bot.duel_runner = runner
    return bot


def _executeur(bot, badges, overlay=True):
    return make_tool_executor(bot, platform="twitch", user_id="9", author="qui",
                              channel="azrael_ttv", badges=badges, overlay=overlay)


def _verdict_evt(**extra):
    donnees = {"azrael": 4, "viewer": 6, "gagnant": "viewer", "abandon": False,
               "manuel": True, "manches_comptees": 2, "manches": 3,
               "rembourser": True, "scores": [], "camps": {}}
    donnees.update(extra)
    return Evenement("verdict", donnees)


@pytest.mark.asyncio
async def test_un_viewer_ne_peut_pas_terminer_le_duel():
    bot = _bot_avec_duel(_verdict_evt())
    executeur = _executeur(bot, [{"set_id": "subscriber"}])

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    bot.duel_runner.terminer.assert_not_awaited()
    assert reponse["status"] == "rejected"


@pytest.mark.asyncio
async def test_un_moderateur_termine_le_duel_et_le_verdict_est_rendu():
    bot = _bot_avec_duel(_verdict_evt())
    executeur = _executeur(bot, [{"set_id": "moderator"}])

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    bot.duel_runner.terminer.assert_awaited_once()
    assert reponse["status"] == "ok"
    assert "Bob" in reponse["message"]
    assert "2" in reponse["message"], (
        f"le nombre de manches comptées doit être dit : {reponse['message']!r}")


@pytest.mark.asyncio
async def test_un_moderateur_dune_chaine_INVITEE_ne_termine_pas_le_duel_maison():
    """Les badges sont propres à CHAQUE chaîne : un modérateur de chez l'hôte
    porte `moderator` et solderait le duel d'Azraël."""
    bot = _bot_avec_duel(_verdict_evt())
    executeur = _executeur(bot, [{"set_id": "moderator"}], overlay=False)

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    bot.duel_runner.terminer.assert_not_awaited()
    assert reponse["status"] == "rejected"


@pytest.mark.asyncio
async def test_sans_rien_darbitrable_loutil_ne_parle_ni_de_score_ni_de_nul():
    bot = _bot_avec_duel(Evenement("abandon", {
        "rembourser": True, "manches_jouees": 1,
        "motif": "le duel a été clos à la main, et aucun kill n'a pu être compté "
                 "d'aucun côté"}))
    executeur = _executeur(bot, [{"set_id": "broadcaster"}])

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    assert reponse["status"] != "ok"
    message = reponse["message"]
    assert not any(c.isdigit() for c in message), (
        f"aucun chiffre à donner, rien n'a été compté : {message!r}")
    assert "l'emporte" not in message.lower(), f"aucun vainqueur : {message!r}"


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_repete_au_modele():
    bot = _bot_avec_duel(_verdict_evt(remboursement_echoue=True))
    executeur = _executeur(bot, [{"set_id": "broadcaster"}])

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    assert reponse["status"] == "partial"
    assert "ÉCHOU" in reponse["message"].upper()


@pytest.mark.asyncio
async def test_sans_duel_loutil_le_dit_au_lieu_de_se_taire():
    bot = _bot_avec_duel(_verdict_evt())
    bot.duel_runner.duel_en_cours = None
    executeur = _executeur(bot, [{"set_id": "broadcaster"}])

    reponse = json.loads(await executeur("duel_apex", json.dumps({"action": "terminer"})))

    bot.duel_runner.terminer.assert_not_awaited()
    assert reponse["status"] == "nothing"


def test_laction_est_offerte_au_modele():
    """Sans elle dans l'énumération, l'outil refuserait un appel parfaitement
    légitime — et Wally n'aurait aucun moyen de savoir que ça existe."""
    from bot.intelligence.overlay_narrator import DUEL_TOOL_SPEC

    spec = DUEL_TOOL_SPEC["function"]
    assert "terminer" in spec["parameters"]["properties"]["action"]["enum"]
    assert "terminer" in spec["description"], (
        "la description doit dire QUAND s'en servir")
