# tests/test_phase8_cognition_emotions.py
"""Phase 8 de l'audit du 2026-08-10 : cognition et émotions.

M9  — l'intervalle est figé AVANT le sommeil (jusqu'à une heure en idle) et
      rien ne le réveille : cadence adaptative morte après chaque creux.
M10 — un rappel dû est désarmé avant d'être délivré, puis soumis à un tirage
      aléatoire : la nuit, la plupart étaient jetés sans reprise possible.
M11 — `now` capturé avant 30-90 s d'appels LLM puis comparé à une horloge
      fraîche : tous les cooldowns SPEAK sous-estimés d'un tick.
M12 — `updated_at` écrit mais jamais relu : aucun rattrapage du decay au
      redémarrage.
"""
import asyncio
import inspect
import math
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.emotion import EmotionEngine
from bot.intelligence.cognitive_loop import CognitiveLoop


# ────────────────────────────── M9 ──────────────────────────────
def _boucle():
    c = CognitiveLoop.__new__(CognitiveLoop)
    c._running = False
    c._reveil = asyncio.Event()
    c._last_activity_ts = 0.0
    c._last_relevant_activity_ts = 0.0
    c._social_rhythm = None
    c._wake_digest = None
    c._spontaneous = {}
    c._recent_interactions = []
    c._emotion = None
    c._typing_seen = {}
    return c


@pytest.mark.asyncio
async def test_une_sollicitation_ecourte_le_sommeil():
    c = _boucle()
    c._running = True
    c._tick_interval = MagicMock(return_value=3600)   # une heure d'idle
    c._tick = AsyncMock(side_effect=lambda: setattr(c, "_running", False))

    tache = asyncio.create_task(c._run())
    await asyncio.sleep(0)
    c.notify_activity(channel_id=1, author="a", content="wally ?", relevant=True)

    await asyncio.wait_for(tache, timeout=2)          # sans réveil : 1 h d'attente
    c._tick.assert_awaited()


@pytest.mark.asyncio
async def test_le_drapeau_de_reveil_est_rearme_apres_usage():
    c = _boucle()
    c.notify_activity(channel_id=1, author="a", content="x", relevant=True)
    assert c._reveil.is_set()
    c._reveil.clear()
    # Une perception passive ne doit PAS réveiller la cadence.
    c.notify_activity(channel_id=1, author="a", content="x", relevant=False)
    assert not c._reveil.is_set()


@pytest.mark.asyncio
async def test_un_dm_reveille_aussi():
    c = _boucle()
    c.notify_activity(channel_id=1, author="a", content="x", is_dm=True)
    assert c._reveil.is_set()


# ────────────────────────────── M10 ──────────────────────────────
def test_un_rappel_du_echappe_a_l_amortisseur_aleatoire():
    src = inspect.getsource(CognitiveLoop._tick)
    assert "self._social_rhythm is not None and forced_seed is None" in src


# ────────────────────────────── M11 ──────────────────────────────
def test_l_horloge_est_rafraichie_avant_les_cooldowns():
    """Le `now` du haut du tick date d'avant les appels LLM."""
    src = inspect.getsource(CognitiveLoop._tick)
    avant_boucle = src.index("for decision in decisions:")
    fragment = src[:avant_boucle]
    # Une deuxième prise d'horloge doit exister entre le raisonnement et la boucle.
    assert fragment.count("now = time.monotonic()") >= 2


# ────────────────────────────── M12 ──────────────────────────────
def _moteur(lam=0.5):
    config = MagicMock()
    cfg = MagicMock(decay_lambda=lam, boredom_rise_per_hour=0.1)
    config.emotions = {e: cfg for e in ("anger", "joy", "sadness", "curiosity", "boredom")}
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    return config


@pytest.mark.asyncio
async def test_une_colere_sauvee_la_nuit_a_decru_au_reveil():
    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.8})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.fetch_all = AsyncMock(return_value=[])
    # Sauvegardée il y a 12 heures.
    db.load_emotion_state_age = AsyncMock(return_value=time.time() - 12 * 3600)

    m = EmotionEngine(_moteur(lam=0.5), db=db)
    await m.load_state()

    attendu = 0.8 * math.exp(-0.5 * 12)
    assert m.get_state()["anger"] == pytest.approx(attendu, abs=0.01)
    assert m.get_state()["anger"] < 0.8


@pytest.mark.asyncio
async def test_un_redemarrage_immediat_ne_change_presque_rien():
    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.8})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.fetch_all = AsyncMock(return_value=[])
    db.load_emotion_state_age = AsyncMock(return_value=time.time() - 5)

    m = EmotionEngine(_moteur(lam=0.5), db=db)
    await m.load_state()
    assert m.get_state()["anger"] == pytest.approx(0.8, abs=0.001)


@pytest.mark.asyncio
async def test_sans_horodatage_l_etat_est_pris_tel_quel():
    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.8})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.fetch_all = AsyncMock(return_value=[])
    db.load_emotion_state_age = AsyncMock(return_value=None)

    m = EmotionEngine(_moteur(), db=db)
    await m.load_state()
    assert m.get_state()["anger"] == 0.8


@pytest.mark.asyncio
async def test_un_horodatage_illisible_ne_bloque_pas_le_boot():
    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.4})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.fetch_all = AsyncMock(return_value=[])
    db.load_emotion_state_age = AsyncMock(side_effect=RuntimeError("colonne absente"))

    m = EmotionEngine(_moteur(), db=db)
    await m.load_state()
    assert m.get_state()["anger"] == 0.4
