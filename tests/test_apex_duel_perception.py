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
    d = _duel()
    d.scores = [{"azrael": None, "viewer": None}]
    bloc = bloc_duel_en_cours(d)
    assert "0" not in bloc.split("Manche")[1][:40], "ne jamais afficher 0 pour une absence"


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
