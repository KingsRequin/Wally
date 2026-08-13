"""Annuler une redemption REND les points au viewer (statut CANCELED).

Chaque refus du duel doit rembourser : un viewer qui a payé et ne voit rien
est le pire résultat possible.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bid", broadcaster_id="123")
    client = MagicMock()
    client.patch = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = str(payload)
    return r


@pytest.mark.asyncio
async def test_remboursement_reussi(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"status": "CANCELED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is True
    _, kwargs = client.patch.call_args
    assert kwargs["json"] == {"status": "CANCELED"}
    assert kwargs["params"]["reward_id"] == "rw"
    assert kwargs["params"]["id"] == "rd"


@pytest.mark.asyncio
async def test_un_200_qui_ne_dit_pas_CANCELED_est_un_echec(monkeypatch):
    """Sur Helix, un 200 ne prouve pas que l'ordre est passé — ce projet l'a
    déjà payé avec is_sent. On lit le CORPS."""
    api, client = _api(_resp(200, {"data": [{"status": "UNFULFILLED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_corps_vide_est_un_echec(monkeypatch):
    api, client = _api(_resp(200, {"data": []}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_erreur_http_ne_leve_pas(monkeypatch):
    api, client = _api(_resp(403, {"error": "Forbidden"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False
