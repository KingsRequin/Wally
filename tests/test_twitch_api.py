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


@pytest.mark.asyncio
async def test_send_message_with_reply_parent():
    """reply_parent_message_id is included in the JSON body when provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello", reply_parent_message_id="msg-abc-123")
    body = mock_http.post.call_args.kwargs["json"]
    assert body["reply_parent_message_id"] == "msg-abc-123"


@pytest.mark.asyncio
async def test_send_message_without_reply_parent_omits_field():
    """reply_parent_message_id is NOT in the JSON body when not provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello")
    body = mock_http.post.call_args.kwargs["json"]
    assert "reply_parent_message_id" not in body


# --- get_last_clip : le plus récent, éventuellement d'une personne précise ---
#
# Helix trie les clips par nombre de vues et ne sait PAS filtrer par créateur :
# les deux tris se font ici.

CLIPS = [
    {"id": "a", "creator_name": "KingsRequin", "created_at": "2026-08-08T10:00:00Z"},
    {"id": "b", "creator_name": "Azrael", "created_at": "2026-08-08T09:00:00Z"},
    {"id": "c", "creator_name": "azrael_ttv", "created_at": "2026-08-07T20:00:00Z"},
]


@pytest.mark.asyncio
async def test_get_last_clip_prend_le_plus_recent():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert (await api.get_last_clip())["id"] == "a"


@pytest.mark.asyncio
async def test_get_last_clip_filtre_sur_le_clippeur():
    """« le dernier clip fait par azra » : le plus récent d'Azrael, pas celui
    de la chaîne."""
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert (await api.get_last_clip(creator="azra"))["id"] == "b"


@pytest.mark.asyncio
async def test_get_last_clip_sans_clip_de_cette_personne():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=CLIPS)
    assert await api.get_last_clip(creator="taki") is None


@pytest.mark.asyncio
async def test_get_last_clip_sans_aucun_clip():
    api = make_api()
    api.get_recent_clips = AsyncMock(return_value=[])
    assert await api.get_last_clip() is None
