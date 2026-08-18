"""Wally ouvre une prédiction, et la résout tout seul sur les kills (§13).

Deux usages dans un seul outil :

  · **libre** — « pariez sur X », Wally compose les choix, quelqu'un tranche à la
    main plus tard ;
  · **kills** — « combien de kills Azraël va faire ? », et là Wally RÉSOUT
    lui-même avec le bilan de fin de partie (§12).

Arbitré avec l'owner : c'est **Wally qui compose les tranches**, pas une table en
dur. Mais pour qu'il puisse résoudre, chaque choix doit porter ses bornes — et le
découpage doit couvrir tous les cas SANS TROU NI RECOUVREMENT. Un pari sur
« 0-2 / 4-6 » laisserait 3 kills sans gagnant, et les points bloqués.

Et quand le résultat n'est pas mesurable (compteurs figés, Mixtape), on ANNULE :
Twitch rembourse tout le monde. Résoudre au hasard punirait des gens qui avaient
raison.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _bot(*, cree=True):
    bot = MagicMock()
    bot.twitch_api.creer_prediction = AsyncMock(return_value={
        "id": "pred-1", "title": "Combien de kills ?",
        "outcomes": [{"id": "o1", "title": "0-2"}, {"id": "o2", "title": "3-5"},
                     {"id": "o3", "title": "6+"}],
    } if cree else None)
    bot.twitch_api.resoudre_prediction = AsyncMock(return_value=True)
    bot.twitch_api.annuler_prediction = AsyncMock(return_value=True)
    # Un bot neuf n'a pas encore de suivi : sans ce `None`, `MagicMock` en
    # fabrique un à la volée et l'outil croit en trouver un vrai.
    bot.prediction_kills = None
    return bot


_TRANCHES = [{"label": "0-2", "min": 0, "max": 2},
             {"label": "3-5", "min": 3, "max": 5},
             {"label": "6+", "min": 6}]


# ── le découpage doit être résolvable ───────────────────────────────────────

def test_un_decoupage_COMPLET_est_accepte():
    from bot.core.prediction_kills import verifier_tranches
    assert verifier_tranches(_TRANCHES) is None


def test_un_TROU_est_refuse_avec_ce_qui_manque():
    """« 0-2 / 4-6 » : trois kills n'ont aucun gagnant, et les points restent
    bloqués. Le message doit dire QUOI corriger — Wally réessaiera."""
    from bot.core.prediction_kills import verifier_tranches
    # Une SEULE faute dans ce cas : le trou. (Le dernier choix est bien ouvert,
    # sinon deux reproches se disputeraient le message.)
    faute = verifier_tranches([{"label": "0-2", "min": 0, "max": 2},
                               {"label": "4+", "min": 4}])
    assert faute and "3" in faute


def test_un_RECOUVREMENT_est_refuse():
    """Deux choix gagnants pour 3 kills : Twitch n'en accepte qu'un, et l'autre
    moitié des pariés se sentira volée."""
    from bot.core.prediction_kills import verifier_tranches
    assert verifier_tranches([{"label": "0-3", "min": 0, "max": 3},
                              {"label": "3+", "min": 3}]) is not None


def test_il_faut_couvrir_les_GROS_scores():
    """Sans borne ouverte à la fin, une partie à 15 kills n'a pas de gagnant."""
    from bot.core.prediction_kills import verifier_tranches
    assert verifier_tranches([{"label": "0-2", "min": 0, "max": 2},
                              {"label": "3-5", "min": 3, "max": 5}]) is not None


def test_il_faut_partir_de_ZERO():
    """Mourir sans tuer est le cas le plus commenté : il doit avoir son choix."""
    from bot.core.prediction_kills import verifier_tranches
    assert verifier_tranches([{"label": "1-2", "min": 1, "max": 2},
                              {"label": "3+", "min": 3}]) is not None


def test_le_choix_gagnant_se_trouve_par_les_BORNES():
    from bot.core.prediction_kills import tranche_gagnante
    assert tranche_gagnante(_TRANCHES, 0)["label"] == "0-2"
    assert tranche_gagnante(_TRANCHES, 4)["label"] == "3-5"
    assert tranche_gagnante(_TRANCHES, 42)["label"] == "6+"


# ── ouvrir ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ouvrir_une_prediction_sur_les_kills():
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    out = await p.ouvrir(bot, "Combien de kills ?", _TRANCHES, 120)
    assert out["ok"] is True
    bot.twitch_api.creer_prediction.assert_awaited_once()
    assert p.en_cours is not None


@pytest.mark.asyncio
async def test_un_decoupage_BANCAL_n_ouvre_RIEN():
    """Le refus arrive AVANT l'appel à Twitch : une prédiction ouverte qu'on ne
    saurait pas résoudre bloquerait les points de tout le monde."""
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    out = await p.ouvrir(bot, "Combien ?", [{"label": "0-2", "min": 0, "max": 2}], 120)
    assert out["ok"] is False
    bot.twitch_api.creer_prediction.assert_not_awaited()


@pytest.mark.asyncio
async def test_deux_predictions_en_meme_temps_c_est_NON():
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    await p.ouvrir(bot, "Combien ?", _TRANCHES, 120)
    out = await p.ouvrir(bot, "Encore ?", _TRANCHES, 120)
    assert out["ok"] is False
    assert "cours" in out["raison"].lower()


@pytest.mark.asyncio
async def test_un_REFUS_de_twitch_ne_laisse_pas_de_prediction_fantome():
    """Sinon la suivante serait refusée « une prédiction est déjà en cours »
    alors qu'il n'y en a aucune."""
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    out = await p.ouvrir(_bot(cree=False), "Combien ?", _TRANCHES, 120)
    assert out["ok"] is False
    assert p.en_cours is None


# ── résoudre sur le bilan de partie ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_fin_de_partie_RESOUT_la_prediction():
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    await p.ouvrir(bot, "Combien de kills ?", _TRANCHES, 120)
    resolu = await p.sur_bilan(bot, {"partie": 4})
    assert resolu is True
    bot.twitch_api.resoudre_prediction.assert_awaited_once_with("pred-1", "o2")
    assert p.en_cours is None          # elle ne traîne pas


@pytest.mark.asyncio
async def test_une_partie_NON_MESURABLE_annule_et_rembourse():
    """Choix de l'owner. Compteurs figés ou Mixtape : personne ne peut dire qui
    avait raison, donc tout le monde récupère ses points."""
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    await p.ouvrir(bot, "Combien de kills ?", _TRANCHES, 120)
    await p.sur_bilan(bot, {"partie": None})
    bot.twitch_api.annuler_prediction.assert_awaited_once_with("pred-1")
    bot.twitch_api.resoudre_prediction.assert_not_awaited()
    assert p.en_cours is None


@pytest.mark.asyncio
async def test_sans_prediction_ouverte_une_fin_de_partie_ne_fait_RIEN():
    from bot.core.prediction_kills import PredictionKills
    bot = _bot()
    assert await PredictionKills().sur_bilan(bot, {"partie": 4}) is False
    bot.twitch_api.resoudre_prediction.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_resolution_REFUSEE_ne_perd_pas_la_prediction():
    """Twitch peut refuser (prédiction déjà close, réseau). La garder permet de
    réessayer à la partie suivante plutôt que de l'abandonner avec les points
    des viewers dedans."""
    from bot.core.prediction_kills import PredictionKills
    p = PredictionKills()
    bot = _bot()
    bot.twitch_api.resoudre_prediction = AsyncMock(return_value=False)
    await p.ouvrir(bot, "Combien de kills ?", _TRANCHES, 120)
    assert await p.sur_bilan(bot, {"partie": 4}) is False
    assert p.en_cours is not None


# ── l'outil du chat ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_MODERATEUR_ouvre_un_pari():
    from bot.core.prediction_kills import run_prediction_tool
    bot = _bot()
    out = await run_prediction_tool(
        bot, {"titre": "Combien de kills ?", "choix": _TRANCHES, "secondes": 120},
        roles=["moderator"])
    assert "ouvert" in out.lower() or "pari" in out.lower()


@pytest.mark.asyncio
async def test_un_VIEWER_se_fait_charrier():
    """Comme pour la musique et le vocal : l'autorisation vient des badges, et
    le refus dit au modèle quoi en faire."""
    from bot.core.prediction_kills import run_prediction_tool
    bot = _bot()
    out = await run_prediction_tool(
        bot, {"titre": "Un pari", "choix": _TRANCHES}, roles=[])
    assert "moque" in out.lower() or "charri" in out.lower()
    bot.twitch_api.creer_prediction.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_chaine_INVITEE_n_ouvre_pas_de_pari_chez_azrael():
    from bot.core.prediction_kills import run_prediction_tool
    bot = _bot()
    out = await run_prediction_tool(
        bot, {"titre": "Un pari", "choix": _TRANCHES}, roles=["moderator"],
        maison=False)
    assert "refus" in out.lower()
    bot.twitch_api.creer_prediction.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_decoupage_BANCAL_est_RENVOYE_au_modele_pour_correction():
    """Le message est lu par Wally : il doit dire ce qui cloche, sinon il
    réessaie à l'identique et personne ne comprend."""
    from bot.core.prediction_kills import run_prediction_tool
    bot = _bot()
    out = await run_prediction_tool(
        bot, {"titre": "Combien ?",
              "choix": [{"label": "1-2", "min": 1, "max": 2},
                        {"label": "3+", "min": 3}]},
        roles=["admin"])
    assert "zéro" in out.lower()
    bot.twitch_api.creer_prediction.assert_not_awaited()


def test_l_outil_demande_les_BORNES_de_chaque_choix():
    """Sans elles, Wally ne peut pas résoudre : c'est ce qui distingue ce pari
    d'un sondage."""
    from bot.core.prediction_kills import PREDICTION_TOOL

    choix = PREDICTION_TOOL["function"]["parameters"]["properties"]["choix"]
    props = choix["items"]["properties"]
    assert {"label", "min"} <= set(props)
    assert "max" in props


# ── le câblage ──────────────────────────────────────────────────────────────

def test_l_outil_est_offert_sur_la_chaine_maison():
    import inspect

    from bot.twitch import handlers

    source = inspect.getsource(handlers)
    assert "PREDICTION_TOOL" in source
    assert 'if name == "open_prediction":' in source


def test_les_roles_viennent_des_BADGES_du_message():
    import inspect
    import re

    from bot.twitch import handlers

    bloc = re.search(r'if name == "open_prediction":(.{0,300})',
                     inspect.getsource(handlers), re.S).group(1)
    assert "_resolve_twitch_roles" in bloc and "badges" in bloc


def test_la_fin_de_partie_solde_le_pari_ET_affiche_le_bilan():
    """Le même bilan sert aux deux (§12 et §13). Si le §13 n'était pas branché,
    un pari ouvert resterait ouvert pour toujours — avec les points dedans."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bot" / "main.py").read_text(encoding="utf-8")
    assert "_solder_pari_sur_partie" in source
    assert "_afficher_bilan_partie(discord_bot, bilan)" in source
