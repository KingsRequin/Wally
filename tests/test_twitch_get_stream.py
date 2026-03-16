import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from bot.twitch.api import TwitchAPI


@pytest.fixture
def api():
    tm = MagicMock()
    tm.bot_token = "fake_token"
    return TwitchAPI(
        token_manager=tm,
        client_id="client123",
        bot_id="bot456",
        broadcaster_id="broadcaster789",
    )


async def test_get_stream_live(api):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{
            "title": "Coding stream",
            "game_name": "Software and Game Development",
            "viewer_count": 42,
            "started_at": "2026-03-16T10:00:00Z",
        }]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is True
    assert result["title"] == "Coding stream"
    assert result["category"] == "Software and Game Development"
    assert result["viewers"] == 42
    assert result["started_at"] == "2026-03-16T10:00:00Z"


async def test_get_stream_offline(api):
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is False
    assert result["title"] is None
    assert result["viewers"] == 0


async def test_get_stream_error_returns_offline(api):
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        mock_client_cls.return_value = mock_client

        result = await api.get_stream()

    assert result["live"] is False
