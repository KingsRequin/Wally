# tests/test_overlay_etat_partie_persist.py
"""Une partie de l'overlay survit à un redémarrage, tant que le live continue.

Constaté en direct le 2026-08-14 : quatre bingos ouverts dans la journée
(09:20, 12:13, 20:06, 22:06), un redémarrage du process entre chaque, et les
deux derniers dans le MÊME live. Sa propre pensée de 22:06:32 dit pourquoi :

    « Est-ce que j'ai déjà ouvert le bingo ? Je ne vois pas de trace dans
      "Sur ton overlay" ni dans "Ce que TU viens de faire" »

Les deux blocs sur lesquels il fonde sa décision vivaient en mémoire du
process. La garde `game_already_running` (2026-08-13) est juste, mais elle ne
protège que dans le process qui a ouvert la partie : un rebuild passe à travers,
et il rouvre — jusqu'à se faire reprendre par le streamer dans son propre chat.

Le patron est celui, déjà éprouvé ici, du mode test (`force_live`).
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.core.secret_guard import redact, release_secret
from bot.intelligence.overlay_narrator import LIVE_STATE_KEY, OverlayNarrator

DEBUT = "2026-08-14T18:00:00Z"


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _narrateur(db=None, live=True, debut=DEBUT):
    return OverlayNarrator(
        OverlayFeed(), AsyncMock(), lambda: live, db=db,
        stream_status=lambda: {"live": live, "started_at": debut},
    )


async def _redemarrage(state, *, live=True, debut=DEBUT):
    """Le process suivant : narrateur neuf, même base."""
    suivant = _narrateur(db=state, live=live, debut=debut)
    await suivant.restore_live_state()
    return suivant


@pytest.mark.asyncio
async def test_le_bingo_et_ses_cases_cochees_survivent_au_redemarrage():
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["il blame le ping", "il rage sur un carre", "azra gagne"])
    n.check_bingo(0)
    await n.flush_live_state()

    suivant = await _redemarrage(state)

    assert suivant._bingo is not None
    assert suivant._bingo["cells"][0] == "il blame le ping"
    assert suivant._bingo["done"] == [True, False, False]


@pytest.mark.asyncio
async def test_le_bingo_restaure_bloque_une_nouvelle_grille():
    """Le but de tout ceci : que la garde tienne APRÈS un rebuild."""
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()

    suivant = await _redemarrage(state)

    refus = suivant.game_already_running("bingo", cells=["autre", "grille"])
    assert refus and "tourne DÉJÀ" in refus
    assert suivant.show_widget("bingo", "", cells=["autre", "grille"]) is None
    assert suivant._bingo["cells"] == ["une", "deux", "trois"]


@pytest.mark.asyncio
async def test_la_partie_restauree_ne_se_fait_pas_effacer_par_reset_live():
    """Le piège : `_was_live` repart à False, donc le premier `_live()` d'un
    process neuf voit une transition et appelle `reset_live()`. Sans précaution,
    la restauration était balayée par le tick qui suivait."""
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()

    suivant = await _redemarrage(state)
    bloc = suivant.current_state_block()      # passe par `_live()`

    assert suivant._bingo is not None, "reset_live() a effacé la partie restaurée"
    assert "bingo" in bloc.lower()


@pytest.mark.asyncio
async def test_un_autre_live_n_herite_pas_du_bingo_du_precedent():
    """Le bingo de la veille n'a rien à faire dans le stream d'aujourd'hui."""
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()

    suivant = await _redemarrage(state, debut="2026-08-15T18:00:00Z")

    assert suivant._bingo is None


@pytest.mark.asyncio
async def test_hors_live_rien_n_est_ressuscite():
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()

    suivant = await _redemarrage(state, live=False)

    assert suivant._bingo is None


@pytest.mark.asyncio
async def test_un_bingo_annule_ne_revient_pas():
    """L'annulation est un ordre : elle doit franchir le redémarrage, elle aussi.
    Le 2026-08-14 à 23:00, le streamer a demandé l'arrêt des bingos — le
    ressusciter au rebuild suivant serait pire que de l'avoir oublié."""
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()
    n.cancel("bingo")
    await n.flush_live_state()

    suivant = await _redemarrage(state)

    assert suivant._bingo is None


@pytest.mark.asyncio
async def test_le_pendu_restaure_repose_son_filet():
    """Le mot du pendu ne doit pas ressortir en clair côté viewers. Le filet est
    posé par `start_hangman` ; restaurer la partie sans le reposer publierait le
    mot que la partie entière consiste à cacher."""
    state = _State()
    n = _narrateur(db=state)
    n.start_hangman("rocket league", "un jeu")
    await n.flush_live_state()
    release_secret("rocket league")           # le process d'avant s'en va
    assert "rocket league" in redact("le mot est rocket league")

    suivant = await _redemarrage(state)

    assert suivant._hangman is not None
    assert "rocket league" not in redact("le mot est rocket league")
    suivant._release_hangman_secret()          # ne pas fuiter sur les autres tests


@pytest.mark.asyncio
async def test_l_objectif_du_live_survit_aussi():
    state = _State()
    n = _narrateur(db=state)
    n._goal = {"label": "10 follows", "count": 3, "target": 10, "kind": "follow"}
    await n.flush_live_state()

    suivant = await _redemarrage(state)

    assert suivant._goal["count"] == 3
    assert suivant._goal["label"] == "10 follows"


@pytest.mark.asyncio
async def test_sans_base_tout_marche_comme_avant():
    n = _narrateur()
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()                 # ne lève pas
    await n.restore_live_state()
    assert n._bingo is not None


@pytest.mark.asyncio
async def test_une_valeur_illisible_est_ignoree():
    suivant = await _redemarrage(_State({LIVE_STATE_KEY: "n'importe quoi"}))
    assert suivant._bingo is None


@pytest.mark.asyncio
async def test_un_etat_vide_n_ecrase_rien_et_ne_leve_pas():
    state = _State({LIVE_STATE_KEY: json.dumps({"stream_key": DEBUT})})
    suivant = await _redemarrage(state)
    assert suivant._bingo is None
    assert suivant._hangman is None
    assert suivant._goal is None


# ── Le rangement part tout seul ──

@pytest.mark.asyncio
async def test_ouvrir_un_bingo_range_l_etat_sans_qu_on_le_demande():
    """En prod, personne n'appelle `flush_live_state()` : c'est la mutation qui
    doit ranger. Un test qui flushe toujours à la main validerait un code qui
    n'écrit jamais rien."""
    state = _State()
    n = _narrateur(db=state)

    n.start_bingo(["une", "deux", "trois"])
    await asyncio.sleep(0)          # laisse partir la tâche de rangement

    assert LIVE_STATE_KEY in state.rows
    assert json.loads(state.rows[LIVE_STATE_KEY])["bingo"]["cells"][0] == "une"


@pytest.mark.asyncio
async def test_cocher_une_case_range_l_etat_sans_qu_on_le_demande():
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    n.check_bingo(1)
    await asyncio.sleep(0)

    assert json.loads(state.rows[LIVE_STATE_KEY])["bingo"]["done"] == [False, True, False]


@pytest.mark.asyncio
async def test_annuler_range_l_effacement_sans_qu_on_le_demande():
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await asyncio.sleep(0)
    n.cancel("bingo")
    await asyncio.sleep(0)

    assert json.loads(state.rows[LIVE_STATE_KEY])["bingo"] is None


# ── Le live pas encore identifié au démarrage ──

@pytest.mark.asyncio
async def test_reprise_quand_le_statut_du_stream_n_est_pas_encore_revenu():
    """Le cas RÉEL du rebuild : `restore_live_state()` tourne dans le `on_ready`
    de Discord, avant que le poll Twitch (60 s) n'ait rempli `_stream_info`.
    `_stream_key()` rend alors "" — exiger l'égalité stricte ferait échouer la
    reprise dans le cas même qu'elle vise."""
    state = _State()
    n = _narrateur(db=state)
    n.start_bingo(["une", "deux", "trois"])
    await n.flush_live_state()

    suivant = await _redemarrage(state, debut="")   # statut pas encore connu

    assert suivant._bingo is not None


@pytest.mark.asyncio
async def test_un_etat_trop_vieux_ne_revient_pas_faute_de_cle():
    """Sans clé de live pour trancher, l'âge tranche : le bingo d'hier soir ne
    doit pas réapparaître sur le live de ce soir."""
    from bot.intelligence.overlay_narrator import _LIVE_STATE_MAX_AGE_S

    vieux = json.dumps({
        "stream_key": "", "saved_at": time.time() - _LIVE_STATE_MAX_AGE_S - 60,
        "bingo": {"cells": ["une", "deux"], "done": [False, False]},
    })
    suivant = await _redemarrage(_State({LIVE_STATE_KEY: vieux}), debut="")

    assert suivant._bingo is None


@pytest.mark.asyncio
async def test_la_cle_du_live_prime_sur_l_age():
    """Un live long : l'état a des heures, mais c'est le même live."""
    ancien = json.dumps({
        "stream_key": DEBUT, "saved_at": time.time() - 6 * 3600,
        "bingo": {"cells": ["une", "deux"], "done": [True, False]},
    })
    suivant = await _redemarrage(_State({LIVE_STATE_KEY: ancien}))

    assert suivant._bingo["done"] == [True, False]
