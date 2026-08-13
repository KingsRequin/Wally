"""Wally doit pouvoir PARLER du duel, pas seulement l'afficher.

Le piège déjà payé : l'état de l'overlay n'allait qu'au prompt des
conversations, la cognition restait aveugle à ses propres effets et Wally
relançait un bingo déjà en cours. Ce fichier vérifie donc le formatage du
bloc ET son branchement aux DEUX endroits — prompt système et contexte
cognitif — pas seulement l'un des deux.
"""
import pytest

from bot.core.apex import duel_runner
from bot.core.apex.duel import Duel, Etat
from bot.core.apex.duel_runner import DuelRunner, current_duel
from bot.intelligence.prompts import PromptBuilder, bloc_duel_en_cours

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}


@pytest.fixture(autouse=True)
def _reset_active():
    duel_runner._active = None
    yield
    duel_runner._active = None


def _duel():
    d = Duel(viewer_nom="Bob", viewer_uid="42", azrael_uid="7")
    d.etat = Etat.ENTRE_MANCHES
    d.scores = [{"azrael": 4, "viewer": 2}, {"azrael": 0, "viewer": 5}]
    return d


def _activate_runner(duel):
    runner = DuelRunner.__new__(DuelRunner)  # pas d'I/O constructeur
    runner.duel_en_cours = duel
    runner.activate()
    return runner


# ── Formatage pur ──────────────────────────────────────────────────────────

def test_le_bloc_nomme_le_demandeur():
    assert "Bob" in bloc_duel_en_cours(_duel())


def test_le_bloc_donne_le_score_de_CHAQUE_manche():
    bloc = bloc_duel_en_cours(_duel())
    assert "4" in bloc and "2" in bloc and "5" in bloc


def test_le_bloc_donne_le_total():
    bloc = bloc_duel_en_cours(_duel())
    assert "4" in bloc and "7" in bloc  # 4+0 contre 2+5


def test_une_manche_non_mesurable_est_dite_comme_telle():
    """La ligne de SCORE de la manche 1, pas l'en-tête « Manche 2 sur 3. » qui la
    précède : un découpage sur le mauvais segment laisserait passer un « 0 »
    inventé sans jamais faire échouer ce test (revue du 2026-08-13)."""
    d = _duel()
    d.scores = [{"azrael": None, "viewer": None}]
    bloc = bloc_duel_en_cours(d)
    lignes_manche_1 = [l for l in bloc.splitlines() if l.startswith("Manche 1")]
    assert len(lignes_manche_1) == 1, f"ligne de la manche 1 introuvable dans : {bloc!r}"
    ligne = lignes_manche_1[0]
    assert "non mesurable" in ligne
    assert "0" not in ligne, "ne jamais afficher 0 pour une absence"


def test_pas_de_duel_pas_de_bloc():
    assert bloc_duel_en_cours(None) == ""


# ── Accès global (même patron que current_apex_block) ──────────────────────

def test_current_duel_rend_none_sans_runner_actif():
    assert current_duel() is None


def test_current_duel_rend_le_duel_du_runner_actif():
    duel = _duel()
    _activate_runner(duel)
    assert current_duel() is duel


# ── Branchement au prompt système (conversations) ───────────────────────────

def test_le_duel_est_injecte_dans_le_prompt_systeme():
    _activate_runner(_duel())
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Duel Apex en cours" in out
    assert "Bob" in out


def test_pas_de_bloc_duel_dans_le_prompt_sans_duel_actif():
    out = PromptBuilder().build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Duel Apex en cours" not in out


# ── Branchement au contexte cognitif ─────────────────────────────────────────

class _FakeFacts:
    async def search_by_category(self, *a, **k):
        return []

    async def get_latest_by_source(self, *a, **k):
        return None

    async def get_by_user(self, *a, **k):
        return []

    async def sample_random(self, *a, **k):
        return []


def _neutralize_io(monkeypatch):
    import bot.core.system_info as si

    monkeypatch.setattr(si, "read_host_metrics", lambda: None, raising=False)

    async def _no_weather():
        return None

    monkeypatch.setattr(si, "fetch_weather_france", _no_weather, raising=False)


async def test_attention_context_porte_le_duel(monkeypatch):
    """build_context doit voir le duel, pas seulement build_system_prompt —
    sinon la cognition reste aveugle à ce que Wally vient d'annoncer."""
    from bot.intelligence.attention_agent import AttentionAgent

    _neutralize_io(monkeypatch)
    _activate_runner(_duel())
    ctx = await AttentionAgent(_FakeFacts()).build_context({"boredom": 0.1}, [])
    assert ctx.duel_block is not None
    assert "Bob" in ctx.duel_block


async def test_attention_context_sans_duel(monkeypatch):
    from bot.intelligence.attention_agent import AttentionAgent

    _neutralize_io(monkeypatch)
    ctx = await AttentionAgent(_FakeFacts()).build_context({"boredom": 0.1}, [])
    assert ctx.duel_block is None


# ── Revue finale — le TOTAL ne s'affirme pas sur du vide ─────────────────────

def test_aucune_manche_mesurable_ne_donne_JAMAIS_un_total_de_zero():
    """Duel joué en Mixtape : chaque manche est déclarée non mesurable, et la
    ligne de total sommait pourtant `None or 0` sans condition — « Total :
    Azraël 0 — Bob 0 », dans le prompt système comme dans le contexte
    cognitif. C'est le zéro inventé que tout le reste du code évite."""
    d = _duel()
    d.scores = [{"azrael": None, "viewer": None}, {"azrael": None, "viewer": None}]

    lignes = [l for l in bloc_duel_en_cours(d).splitlines() if l.startswith("Total")]

    assert len(lignes) == 1, "le bloc doit dire quelque chose du total, jamais rien"
    assert "0" not in lignes[0], f"un total affirmé sur du vide : {lignes[0]!r}"


def test_un_total_reste_donne_des_qu_une_manche_est_mesuree():
    """L'inverse doit rester vrai : une seule manche mesurée suffit à ce que
    les totaux veuillent dire quelque chose, même si les suivantes sont
    perdues."""
    d = _duel()
    d.scores = [{"azrael": 4, "viewer": 2}, {"azrael": None, "viewer": None}]

    ligne = [l for l in bloc_duel_en_cours(d).splitlines() if l.startswith("Total")][0]

    assert "4" in ligne and "2" in ligne
