"""Renouvellement anticipé des tokens Twitch.

Bug observé en prod (2026-08-06) : `_token_refresh_loop` passe toutes les 3 h et
appelait `startup_validate()`, qui ne renouvelait QUE sur 401. Un token vivant 4 h
était donc jugé « valide » à T+3h (1 h restante), expirait à T+4h, et n'était
repris qu'à T+6h — EventSub cassait deux heures durant, et les souscriptions
streamer (subs, resubs, gifts, cheers) tombaient silencieusement.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.twitch.token_manager import _PROACTIVE_REFRESH_S, TwitchTokenManager


def _tm() -> TwitchTokenManager:
    return TwitchTokenManager(
        env_path=Path("/nonexistent/.env"),
        bot_token="bt", bot_refresh="br",
        streamer_token="st", streamer_refresh="sr",
        client_id="cid", client_secret="sec",
    )


def _validate_response(expires_in: int):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"scopes": ["chat:read"], "expires_in": expires_in}
    return resp


async def _run(tm, expires_in):
    client = MagicMock()
    client.get = AsyncMock(return_value=_validate_response(expires_in))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("bot.twitch.token_manager.httpx.AsyncClient", return_value=client):
        await tm.startup_validate()


def test_la_marge_couvre_l_intervalle_du_cycle():
    """Il faut renouveler avant que 3 h ne s'écoulent, sinon le trou réapparaît."""
    assert _PROACTIVE_REFRESH_S > 3 * 3600


@pytest.mark.asyncio
async def test_un_token_bientot_expire_est_renouvele_sans_attendre_le_401():
    tm = _tm()
    tm.refresh = AsyncMock(return_value=True)
    await _run(tm, expires_in=3600)  # 1 h restante → sous le seuil
    assert tm.refresh.await_count == 2  # bot + streamer


@pytest.mark.asyncio
async def test_un_token_frais_n_est_pas_renouvele_inutilement():
    """Sinon EventSub redémarrerait à chaque cycle pour rien."""
    tm = _tm()
    tm.refresh = AsyncMock(return_value=True)
    await _run(tm, expires_in=4 * 3600)  # token neuf
    tm.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_reponse_sans_expires_in_ne_casse_rien():
    tm = _tm()
    tm.refresh = AsyncMock(return_value=True)
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"scopes": []}
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("bot.twitch.token_manager.httpx.AsyncClient", return_value=client):
        await tm.startup_validate()
    tm.refresh.assert_not_awaited()
