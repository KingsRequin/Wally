# tests/test_overlay_force_live_persist.py
"""Le mode test survit à un redémarrage.

Constaté le 2026-08-08 en pleine séance de réglages : quatre déploiements dans
l'après-midi, et à chaque fois l'overlay redevenait muet. Le mode test vivait en
mémoire, sur une horloge `monotonic` qui repart de zéro à chaque process — il
était donc perdu au moment précis où l'on s'en sert le plus.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import FORCE_LIVE_KEY, OverlayNarrator


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _narrateur(db=None, live=False):
    return OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: live, db=db)


@pytest.mark.asyncio
async def test_le_mode_test_est_range_en_base():
    state = _State()
    n = _narrateur(db=state)
    n.force_live(30)
    await n.flush_force_live()
    assert float(state.rows[FORCE_LIVE_KEY]) > time.time()


@pytest.mark.asyncio
async def test_il_est_repris_au_demarrage_suivant():
    """Le nouveau process doit se croire encore en mode test."""
    state = _State({FORCE_LIVE_KEY: str(time.time() + 600)})
    n = _narrateur(db=state)
    assert n.is_active() is False          # pas encore rechargé
    await n.restore_force_live()
    assert n.is_active() is True
    assert 9 < n.force_live_remaining() <= 10


@pytest.mark.asyncio
async def test_une_echeance_depassee_ne_ressuscite_pas():
    """Un mode test expiré pendant l'arrêt reste expiré."""
    state = _State({FORCE_LIVE_KEY: str(time.time() - 60)})
    n = _narrateur(db=state)
    await n.restore_force_live()
    assert n.is_active() is False


@pytest.mark.asyncio
async def test_couper_le_mode_test_l_efface_aussi_en_base():
    state = _State({FORCE_LIVE_KEY: str(time.time() + 600)})
    n = _narrateur(db=state)
    await n.restore_force_live()
    n.force_live(0)
    await n.flush_force_live()
    assert n.is_active() is False
    assert float(state.rows[FORCE_LIVE_KEY] or 0) == 0


@pytest.mark.asyncio
async def test_sans_base_le_mode_test_marche_comme_avant():
    n = _narrateur()
    n.force_live(30)
    assert n.is_active() is True
    await n.flush_force_live()             # ne lève pas
    await n.restore_force_live()


@pytest.mark.asyncio
async def test_une_valeur_illisible_est_ignoree():
    n = _narrateur(db=_State({FORCE_LIVE_KEY: "n'importe quoi"}))
    await n.restore_force_live()
    assert n.is_active() is False


@pytest.mark.asyncio
async def test_un_vrai_live_reste_prioritaire():
    n = _narrateur(db=_State(), live=True)
    assert n.is_active() is True
