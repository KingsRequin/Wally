"""Tests for TwitchTokenManager — token validation, refresh, and .env persistence."""
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from bot.twitch.token_manager import TwitchTokenManager


def make_manager(tmp_path: Path, bot_token="bot123", bot_refresh="botref",
                 streamer_token="str123", streamer_refresh="strref") -> TwitchTokenManager:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"BOT_ACCESS_TOKEN={bot_token}\n"
        f"BOT_REFRESH_TOKEN={bot_refresh}\n"
        f"STREAMER_ACCESS_TOKEN={streamer_token}\n"
        f"STREAMER_REFRESH_TOKEN={streamer_refresh}\n"
        "TWITCH_CLIENT_ID=cid\n"
        "TWITCH_CLIENT_SECRET=csec\n"
    )
    return TwitchTokenManager(
        env_path=env_file,
        bot_token=bot_token,
        bot_refresh=bot_refresh,
        streamer_token=streamer_token,
        streamer_refresh=streamer_refresh,
        client_id="cid",
        client_secret="csec",
    )


def make_validate_response(status=200, scopes=None, expires_in=14000):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"scopes": scopes or ["user:read:chat"], "expires_in": expires_in}
    resp.raise_for_status = MagicMock()
    return resp


def make_refresh_response(new_token="new_access", new_refresh="new_refresh"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": new_token, "refresh_token": new_refresh}
    resp.raise_for_status = MagicMock()
    return resp


# ── load ──────────────────────────────────────────────────────────────────────

def test_load_reads_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_ACCESS_TOKEN", "bat")
    monkeypatch.setenv("BOT_REFRESH_TOKEN", "brt")
    monkeypatch.setenv("STREAMER_ACCESS_TOKEN", "sat")
    monkeypatch.setenv("STREAMER_REFRESH_TOKEN", "srt")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "cid")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "csec")
    env_file = tmp_path / ".env"
    env_file.write_text("")
    mgr = TwitchTokenManager.load(env_file)
    assert mgr.bot_token == "bat"
    assert mgr._bot_refresh == "brt"
    assert mgr.streamer_token == "sat"
    assert mgr._streamer_refresh == "srt"
    assert mgr._client_id == "cid"
    assert mgr._client_secret == "csec"


# ── startup_validate ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_success_logs_no_error(tmp_path, caplog):
    mgr = make_manager(tmp_path)
    ok = make_validate_response(status=200)
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=ok)
        await mgr.startup_validate()
    # No refresh triggered — tokens were valid
    assert mgr.bot_token == "bot123"
    assert mgr.streamer_token == "str123"


@pytest.mark.asyncio
async def test_validate_401_triggers_refresh(tmp_path):
    mgr = make_manager(tmp_path)
    invalid = make_validate_response(status=401)
    refresh_ok = make_refresh_response("new_bot", "new_botref")
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.get = AsyncMock(return_value=invalid)
        mock_http.post = AsyncMock(return_value=refresh_ok)
        await mgr.startup_validate()
    assert mgr.bot_token == "new_bot"


# ── refresh ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_bot_updates_memory(tmp_path):
    mgr = make_manager(tmp_path)
    ok = make_refresh_response("fresh_access", "fresh_refresh")
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=ok)
        result = await mgr.refresh("bot")
    assert result is True
    assert mgr.bot_token == "fresh_access"


@pytest.mark.asyncio
async def test_refresh_streamer_updates_memory(tmp_path):
    mgr = make_manager(tmp_path)
    ok = make_refresh_response("fresh_str", "fresh_strref")
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=ok)
        result = await mgr.refresh("streamer")
    assert result is True
    assert mgr.streamer_token == "fresh_str"


@pytest.mark.asyncio
async def test_refresh_writes_env_atomically(tmp_path):
    mgr = make_manager(tmp_path)
    ok = make_refresh_response("tok_new", "ref_new")
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=ok)
        await mgr.refresh("bot")
    content = (tmp_path / ".env").read_text()
    assert "BOT_ACCESS_TOKEN=tok_new" in content
    assert "BOT_REFRESH_TOKEN=ref_new" in content
    # tmp file must have been renamed away
    assert not (tmp_path / ".env.tmp").exists()


@pytest.mark.asyncio
async def test_refresh_returns_false_on_http_error(tmp_path):
    mgr = make_manager(tmp_path)
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("network error")
        )
        result = await mgr.refresh("bot")
    assert result is False
    assert mgr.bot_token == "bot123"  # unchanged


@pytest.mark.asyncio
async def test_refresh_returns_false_without_refresh_token(tmp_path):
    mgr = make_manager(tmp_path, bot_refresh="")
    result = await mgr.refresh("bot")
    assert result is False


@pytest.mark.asyncio
async def test_refresh_returns_false_without_client_secret(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_ACCESS_TOKEN=x\nBOT_REFRESH_TOKEN=r\n")
    mgr = TwitchTokenManager(env_file, "x", "r", "", "", "cid", "")
    result = await mgr.refresh("bot")
    assert result is False


@pytest.mark.asyncio
async def test_startup_validate_skips_gracefully_when_tokens_empty(tmp_path):
    """startup_validate must not raise when both tokens are empty strings."""
    env_file = tmp_path / ".env"
    env_file.write_text("")
    mgr = TwitchTokenManager(env_file, "", "", "", "", "cid", "csec")
    # Should return without calling httpx at all
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        await mgr.startup_validate()
    MockClient.assert_not_called()
    # Tokens remain empty — caller (main.py) checks bot_token after this call
    assert mgr.bot_token == ""


@pytest.mark.asyncio
async def test_write_env_appends_key_when_absent(tmp_path):
    """_write_env must append the key if not already present in .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_VAR=value\n")  # no BOT_ACCESS_TOKEN line
    mgr = TwitchTokenManager(env_file, "old", "old_ref", "", "", "cid", "csec")
    ok = make_refresh_response("appended_token", "appended_ref")
    with patch("bot.twitch.token_manager.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=ok)
        await mgr.refresh("bot")
    content = env_file.read_text()
    assert "BOT_ACCESS_TOKEN=appended_token" in content
    assert "BOT_REFRESH_TOKEN=appended_ref" in content
