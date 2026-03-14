"""Tests for TwitchAPI.send_message — Helix POST with 401 retry."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.twitch.api import TwitchAPI


def make_api(bot_token="bot_tok") -> TwitchAPI:
    tm = MagicMock()
    tm.bot_token = bot_token
    tm.refresh = AsyncMock(return_value=True)
    return TwitchAPI(
        token_manager=tm,
        client_id="cid",
        bot_id="bot_id",
        broadcaster_id="bc_id",
    )


def make_http_response(status=200):
    resp = MagicMock()
    resp.status_code = status
    if status == 200:
        resp.raise_for_status = MagicMock()
    else:
        import httpx as _httpx
        resp.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError(
                f"HTTP {status}", request=MagicMock(), response=MagicMock()
            )
        )
    return resp


@pytest.mark.asyncio
async def test_send_message_calls_helix():
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello world")
    mock_http.post.assert_awaited_once()
    call_kwargs = mock_http.post.call_args
    body = call_kwargs.kwargs["json"]
    assert body["broadcaster_id"] == "bc_id"
    assert body["sender_id"] == "bot_id"
    assert body["message"] == "hello world"


@pytest.mark.asyncio
async def test_send_message_uses_bot_token_in_header():
    api = make_api(bot_token="my_token")
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("test")
    headers = mock_http.post.call_args.kwargs["headers"]
    assert "Bearer my_token" in headers["Authorization"]


@pytest.mark.asyncio
async def test_send_message_retries_on_401():
    api = make_api()
    unauthorized = make_http_response(401)
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(side_effect=[unauthorized, ok])
        await api.send_message("retry me")
    assert mock_http.post.await_count == 2
    api._tm.refresh.assert_awaited_once_with("bot")


@pytest.mark.asyncio
async def test_send_message_gives_up_after_second_401():
    api = make_api()
    unauthorized = make_http_response(401)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(side_effect=[unauthorized, unauthorized])
        await api.send_message("fail")
    assert mock_http.post.await_count == 2
    api._tm.refresh.assert_awaited_once_with("bot")


@pytest.mark.asyncio
async def test_send_message_no_retry_if_refresh_fails():
    api = make_api()
    api._tm.refresh = AsyncMock(return_value=False)
    unauthorized = make_http_response(401)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=unauthorized)
        await api.send_message("fail")
    assert mock_http.post.await_count == 1
