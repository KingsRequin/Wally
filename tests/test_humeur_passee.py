"""Wally se souvient de ses propres humeurs.

Un état émotionnel sans mémoire n'est pas un caractère, c'est une météo. Tout
était enregistré — `emotion_history` et `emotion_peaks` — et il n'en connaissait
que l'instant présent.
"""
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.tools.humeur_passee_tool import run_mood_history_tool


# ⚠️ En Europe/Paris, jamais en heure locale : CT100 tourne en UTC et l'outil
# lit en Paris. Un `datetime.now()` nu décalait chaque assertion de deux heures.
_TZ = ZoneInfo("Europe/Paris")


def _t(jours_avant: float, heure: int = 12) -> float:
    quand = datetime.now(_TZ) - timedelta(days=jours_avant)
    return quand.replace(hour=heure, minute=0, second=0, microsecond=0).timestamp()


def _bot(snapshots=None, pics=None, pseudos=None):
    bot = MagicMock()
    bot.db.get_emotion_snapshots_since = AsyncMock(return_value=snapshots or [])
    bot.db.get_emotion_peaks_since = AsyncMock(return_value=pics or [])
    bot.db.get_memory_username = AsyncMock(
        side_effect=lambda uid: (pseudos or {}).get(uid)
    )
    return bot


def _snap(quand, **emotions):
    base = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    base.update(emotions)
    base["snapshot_at"] = quand
    return base


async def _appel(bot, **args):
    return json.loads(await run_mood_history_tool(bot, args))


# ── Ce qui a culminé, jamais la moyenne ───────────────────────────────────


async def test_rend_le_sommet_du_jour_pas_la_moyenne():
    """Mesuré sur 11 jours réels : la moyenne donne « ennui » dix fois sur onze.
    L'ennui monte tout seul dès que personne ne parle — c'est le bruit de fond."""
    bot = _bot(snapshots=[
        _snap(_t(1, h), boredom=0.9, anger=(0.87 if h == 21 else 0.0))
        for h in range(24)
    ])

    jour = (await _appel(bot, jours=2))["par_jour"][0]

    assert any("colère" in m for m in jour["monte"]), jour


async def test_une_emotion_qui_n_a_rien_vecu_n_est_pas_rendue():
    bot = _bot(snapshots=[_snap(_t(1), joy=0.8, sadness=0.04)])

    monte = (await _appel(bot, jours=2))["par_jour"][0]["monte"]

    assert monte == ["joie au maximum"] or monte == ["joie très fort"]
    assert not any("tristesse" in m for m in monte)


async def test_les_jours_sont_nommes_relativement():
    bot = _bot(snapshots=[_snap(_t(0), joy=0.8), _snap(_t(1), joy=0.8)])

    jours = [j["jour"] for j in (await _appel(bot, jours=2))["par_jour"]]

    assert jours == ["hier", "aujourd'hui"]


async def test_un_jour_sans_rien_le_dit_plutot_que_de_se_taire():
    bot = _bot(snapshots=[_snap(_t(1), joy=0.1)])

    assert (await _appel(bot, jours=2))["par_jour"][0]["monte"] == ["rien de marquant"]


# ── Les moments, et leur diversité ────────────────────────────────────────


async def test_chaque_emotion_garde_un_representant():
    """Prendre les N plus hauts les rendait tous joyeux : la joie pique à 1,00
    presque chaque jour, la colère à 0,87 aurait disparu — et Wally aurait juré
    n'avoir jamais été énervé."""
    pics = [{"timestamp": _t(1, 10 + i), "emotion": "joy", "value": 1.0,
             "trigger_user": "bob", "trigger_message": "lol", "platform": "twitch"}
            for i in range(10)]
    pics.append({"timestamp": _t(1, 21), "emotion": "anger", "value": 0.87,
                 "trigger_user": "bob", "trigger_message": "grr", "platform": "twitch"})
    bot = _bot(pics=pics)

    emotions = {m["emotion"] for m in (await _appel(bot, jours=2))["moments"]}

    assert "colère" in emotions


async def test_un_identifiant_brut_devient_un_pseudo():
    """`trigger_user` est tantôt un pseudo, tantôt un id — selon le site qui a
    écrit le pic."""
    bot = _bot(
        pics=[{"timestamp": _t(1, 21), "emotion": "anger", "value": 0.9,
               "trigger_user": "1068201345", "trigger_message": "grr",
               "platform": "twitch"}],
        pseudos={"twitch:1068201345": "ClakerNoJutsu"},
    )

    assert (await _appel(bot, jours=2))["moments"][0]["declenche_par"] == "ClakerNoJutsu"


async def test_un_identifiant_introuvable_n_est_pas_rendu_tel_quel():
    """Un nombre n'apprend rien au modèle, et il finirait écrit dans le chat."""
    bot = _bot(pics=[{"timestamp": _t(1, 21), "emotion": "anger", "value": 0.9,
                      "trigger_user": "999", "trigger_message": "grr",
                      "platform": "twitch"}])

    moment = (await _appel(bot, jours=2))["moments"][0]

    assert "declenche_par" not in moment


async def test_le_message_declencheur_est_borne():
    bot = _bot(pics=[{"timestamp": _t(1, 21), "emotion": "joy", "value": 0.9,
                      "trigger_user": "bob", "trigger_message": "x" * 500,
                      "platform": "twitch"}])

    assert len((await _appel(bot, jours=2))["moments"][0]["a_propos_de"]) <= 80


async def test_l_heure_du_moment_est_rendue():
    """« T'étais énervé HIER SOIR » — sans l'heure, la réponse rate la question."""
    bot = _bot(pics=[{"timestamp": _t(1, 21), "emotion": "anger", "value": 0.9,
                      "trigger_user": "bob", "trigger_message": "grr",
                      "platform": "twitch"}])

    assert (await _appel(bot, jours=2))["moments"][0]["quand"] == "hier à 21h00"


# ── Bornes et replis ──────────────────────────────────────────────────────


async def test_la_fenetre_demandee_dimensionne_la_requete():
    """`get_emotion_snapshots_since` plafonne à 5 000 et garde les plus RÉCENTES :
    ~310 instantanés par jour, donc 30 jours en perdraient la moitié la plus
    ancienne, sans une erreur."""
    bot = _bot(snapshots=[_snap(_t(1), joy=0.8)])

    await _appel(bot, jours=30)

    assert bot.db.get_emotion_snapshots_since.await_args.kwargs["limit"] >= 30 * 310


@pytest.mark.parametrize(("demande", "attendu_max"), [(0, 1), (999, 30), (-5, 1)])
async def test_la_periode_est_bornee_a_la_retention(demande, attendu_max):
    """Au-delà de 30 jours, `main.py` a purgé : promettre plus rendrait un
    silence qui se lit « il ne s'est rien passé »."""
    bot = _bot(snapshots=[_snap(_t(0), joy=0.8)])

    assert (await _appel(bot, jours=demande))["periode"] == f"{attendu_max} jour(s)"


async def test_hier_veut_dire_la_journee_d_hier_pas_les_24_dernieres_heures():
    bot = _bot(snapshots=[_snap(_t(0), joy=0.8)])
    await _appel(bot, jours=2)

    since = bot.db.get_emotion_snapshots_since.await_args[0][0]
    debut_hier = (datetime.now(_TZ) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    assert abs(since - debut_hier) < 3600


async def test_base_muette_le_dit_au_lieu_d_inventer():
    bot = _bot()
    bot.db.get_emotion_peaks_since.side_effect = RuntimeError("base fermée")

    reponse = await _appel(bot, jours=7)

    assert reponse["status"] == "error"
    assert "invent" in reponse["message"]


async def test_sans_base_l_outil_le_dit():
    bot = MagicMock()
    bot.db = None

    assert (await _appel(bot, jours=7))["status"] == "unavailable"


async def test_rien_en_base_n_est_pas_une_erreur():
    assert (await _appel(_bot(), jours=7))["status"] == "vide"


@pytest.mark.parametrize("jours", ["sept", None, {}])
async def test_un_argument_tordu_retombe_sur_le_defaut(jours):
    bot = _bot(snapshots=[_snap(_t(0), joy=0.8)])

    assert (await _appel(bot, jours=jours))["periode"] == "7 jour(s)"


# ── Le câblage : les trois plateformes ────────────────────────────────────


async def test_l_outil_est_offert_partout_ou_wally_parle():
    """Un outil branché d'un côté et oublié de l'autre ne casse rien et ne
    journalise rien — précédent payé en direct le 2026-08-25."""
    from tests.test_parite_plateformes import _bot_avec_tout, _noms
    from bot.discord.handlers import build_chat_tools as discord
    from bot.discord.voice.tools import build_voice_tools as vocal
    from bot.twitch.handlers import build_chat_tools as twitch

    bot = _bot_avec_tout()
    assert "mood_history" in _noms(await discord(bot, author_id="42"))
    assert "mood_history" in _noms(await twitch(bot))
    assert "mood_history" in _noms(await vocal(bot))
