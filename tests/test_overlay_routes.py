"""Routes de l'overlay : télémétrie de rendu + déclencheur de test."""
import time

import pytest
from fastapi import HTTPException

from bot.core.overlay_feed import OverlayFeed
from bot.dashboard.routes.overlay import get_overlay_health, overlay_health, overlay_test


class _Req:
    """Request minimal : state + body JSON."""
    def __init__(self, state, body=None, bad_json=False):
        self.app = type("A", (), {"state": type("S", (), {"wally": state})()})()
        self._body = body
        self._bad = bad_json

    async def json(self):
        if self._bad:
            raise ValueError("pas du JSON")
        return self._body


def _state():
    return type("W", (), {"overlay_feed": OverlayFeed(), "overlay_health": None})()


# ── télémétrie ──

@pytest.mark.asyncio
async def test_la_telemetrie_est_stockee_et_bornee():
    st = _state()
    await overlay_health(_Req(st, {"fps": 60, "worst_frame_ms": 12, "gpu": "RTX 3060"}))
    assert st.overlay_health["fps"] == 60
    assert st.overlay_health["gpu"] == "RTX 3060"

    # La page est publique : des valeurs hostiles ne doivent pas passer telles
    # quelles (fps aberrant, chaîne GPU interminable).
    await overlay_health(_Req(st, {"fps": 99999, "worst_frame_ms": -5, "gpu": "x" * 500}))
    assert st.overlay_health["fps"] == 240
    assert st.overlay_health["worst_frame_ms"] == 0
    assert len(st.overlay_health["gpu"]) == 120


@pytest.mark.asyncio
async def test_telemetrie_invalide_rejetee():
    st = _state()
    with pytest.raises(HTTPException):
        await overlay_health(_Req(st, {"fps": "beaucoup"}))
    with pytest.raises(HTTPException):
        await overlay_health(_Req(st, bad_json=True))
    assert st.overlay_health is None


@pytest.mark.asyncio
async def test_un_overlay_silencieux_est_vu_deconnecte():
    st = _state()
    assert (await get_overlay_health(_Req(st)))["connected"] is False

    await overlay_health(_Req(st, {"fps": 60, "worst_frame_ms": 8}))
    assert (await get_overlay_health(_Req(st)))["connected"] is True

    st.overlay_health["at"] = time.time() - 60  # plus de nouvelles depuis 60 s
    assert (await get_overlay_health(_Req(st)))["connected"] is False


# ── déclencheur de test ──

@pytest.mark.asyncio
async def test_le_declencheur_publie_sur_le_feed():
    st = _state()
    q = st.overlay_feed.subscribe()
    await overlay_test(_Req(st, {"type": "bubble", "text": "coucou", "mode": "thought"}))
    e = q.get_nowait()
    assert e["type"] == "bubble" and e["mode"] == "thought" and e["text"] == "coucou"


@pytest.mark.asyncio
async def test_declencheur_thinking_et_react():
    st = _state()
    q = st.overlay_feed.subscribe()
    await overlay_test(_Req(st, {"type": "thinking"}))
    await overlay_test(_Req(st, {"type": "react", "kind": "raid"}))
    assert q.get_nowait()["type"] == "thinking"
    assert q.get_nowait()["kind"] == "raid"


@pytest.mark.asyncio
async def test_declencheur_invalide():
    st = _state()
    with pytest.raises(HTTPException):
        await overlay_test(_Req(st, {"type": "bubble", "text": "  "}))
    with pytest.raises(HTTPException):
        await overlay_test(_Req(st, {"type": "inconnu"}))


@pytest.mark.asyncio
async def test_le_declencheur_publie_un_widget():
    st = _state()
    q = st.overlay_feed.subscribe()
    await overlay_test(_Req(st, {
        "type": "widget", "widget": "coinflip", "params": {"result": "tails"},
    }))
    e = q.get_nowait()
    assert e["type"] == "widget" and e["kind"] == "coinflip"
    assert e["params"]["result"] == "tails"


@pytest.mark.asyncio
async def test_widget_sans_nom_rejete():
    st = _state()
    with pytest.raises(HTTPException):
        await overlay_test(_Req(st, {"type": "widget", "widget": "  "}))


@pytest.mark.asyncio
async def test_widget_sans_parametres():
    """params absent ou mal typé ne doit pas casser l'appel."""
    st = _state()
    q = st.overlay_feed.subscribe()
    await overlay_test(_Req(st, {"type": "widget", "widget": "dice", "params": "pas un dict"}))
    assert q.get_nowait()["params"] == {}
