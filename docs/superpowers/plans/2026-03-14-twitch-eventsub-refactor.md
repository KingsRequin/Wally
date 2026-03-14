# Twitch EventSub Refactor — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la connexion IRC de twitchio par EventSub WebSocket + API Helix pour le chat, avec gestion native du refresh token pour les deux comptes (bot + streamer).

**Architecture:** `TwitchTokenManager` gère le cycle de vie des deux tokens (validate, refresh, persistance atomique dans `.env`). `TwitchAPI` encapsule les appels Helix (send_message avec retry 401). `channel.chat.message` est ajouté via un patch runtime de twitchio v2 (absent de ses `SubscriptionTypes`). Plus de connexion IRC — `initial_channels=[]`.

**Tech Stack:** Python 3.11, twitchio v2 (pinné), httpx, pytest-asyncio, unittest.mock, pathlib

**Spec:** `docs/superpowers/specs/2026-03-14-twitch-eventsub-refactor-design.md`

---

## Chunk 1 : TwitchTokenManager

### Task 1: TwitchTokenManager — validate + refresh + atomic .env write

**Files:**
- Create: `bot/twitch/token_manager.py`
- Create: `tests/test_twitch_token_manager.py`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_twitch_token_manager.py
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
```

- [ ] **Step 2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_token_manager.py -v 2>&1 | head -30
```
Attendu : `ModuleNotFoundError: No module named 'bot.twitch.token_manager'`

- [ ] **Step 3 : Implémenter `bot/twitch/token_manager.py`**

```python
# bot/twitch/token_manager.py
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Optional

import httpx
from loguru import logger


class TwitchTokenManager:
    VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"

    def __init__(
        self,
        env_path: Path,
        bot_token: str,
        bot_refresh: str,
        streamer_token: str,
        streamer_refresh: str,
        client_id: str,
        client_secret: str,
    ):
        self._env_path = env_path
        self._bot_token = bot_token
        self._bot_refresh = bot_refresh
        self._streamer_token = streamer_token
        self._streamer_refresh = streamer_refresh
        self._client_id = client_id
        self._client_secret = client_secret

    @property
    def bot_token(self) -> str:
        return self._bot_token

    @property
    def streamer_token(self) -> str:
        return self._streamer_token

    @classmethod
    def load(cls, env_path: Path) -> "TwitchTokenManager":
        return cls(
            env_path=env_path,
            bot_token=os.getenv("BOT_ACCESS_TOKEN", ""),
            bot_refresh=os.getenv("BOT_REFRESH_TOKEN", ""),
            streamer_token=os.getenv("STREAMER_ACCESS_TOKEN", ""),
            streamer_refresh=os.getenv("STREAMER_REFRESH_TOKEN", ""),
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
        )

    async def startup_validate(self) -> None:
        for token_type in ("bot", "streamer"):
            token = self._bot_token if token_type == "bot" else self._streamer_token
            if not token:
                logger.warning("Twitch {t} token not set", t=token_type)
                continue
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        self.VALIDATE_URL,
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=10,
                    )
                if resp.status_code == 401:
                    logger.warning(
                        "Twitch {t} token invalid at startup, refreshing...", t=token_type
                    )
                    await self.refresh(token_type)
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    logger.info(
                        "Twitch {t} token valid — scopes={scopes} expires_in={exp}s",
                        t=token_type,
                        scopes=data.get("scopes", []),
                        exp=data.get("expires_in", "?"),
                    )
            except Exception as exc:
                logger.error(
                    "Twitch {t} token validation error: {e}", t=token_type, e=exc
                )

    async def refresh(self, token_type: Literal["bot", "streamer"]) -> bool:
        refresh_token = (
            self._bot_refresh if token_type == "bot" else self._streamer_refresh
        )
        if not refresh_token:
            logger.error(
                "Cannot refresh Twitch {t} token — refresh token not set", t=token_type
            )
            return False
        if not self._client_id or not self._client_secret:
            logger.error(
                "Cannot refresh Twitch {t} token — CLIENT_ID/SECRET not set",
                t=token_type,
            )
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            new_token: str = data["access_token"]
            new_refresh: str = data["refresh_token"]
            if token_type == "bot":
                self._bot_token = new_token
                self._bot_refresh = new_refresh
            else:
                self._streamer_token = new_token
                self._streamer_refresh = new_refresh
            self._write_env(token_type, new_token, new_refresh)
            logger.info("Twitch {t} token refreshed successfully", t=token_type)
            return True
        except Exception as exc:
            logger.error(
                "Twitch {t} token refresh failed: {e}", t=token_type, e=exc
            )
            return False

    def _write_env(
        self,
        token_type: Literal["bot", "streamer"],
        new_token: str,
        new_refresh: str,
    ) -> None:
        if not self._env_path.exists():
            logger.warning(
                ".env not found at {p}, skipping persistence", p=self._env_path
            )
            return
        if token_type == "bot":
            access_key, refresh_key = "BOT_ACCESS_TOKEN", "BOT_REFRESH_TOKEN"
        else:
            access_key, refresh_key = "STREAMER_ACCESS_TOKEN", "STREAMER_REFRESH_TOKEN"
        content = self._env_path.read_text(encoding="utf-8")

        def _replace_or_append(text: str, key: str, value: str) -> str:
            pattern = rf"^{key}=.*$"
            if re.search(pattern, text, flags=re.MULTILINE):
                return re.sub(pattern, f"{key}={value}", text, flags=re.MULTILINE)
            # Key absent: append at end
            return text.rstrip("\n") + f"\n{key}={value}\n"

        content = _replace_or_append(content, access_key, new_token)
        content = _replace_or_append(content, refresh_key, new_refresh)
        tmp_path = self._env_path.parent / ".env.tmp"
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(self._env_path))
```

- [ ] **Step 4 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_token_manager.py -v
```
Attendu : tous les tests PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/twitch/token_manager.py tests/test_twitch_token_manager.py
git commit -m "feat: add TwitchTokenManager with validate, refresh, and atomic .env write"
```

---

## Chunk 2 : TwitchAPI

### Task 2: TwitchAPI — send_message avec retry 401

**Files:**
- Create: `bot/twitch/api.py`
- Create: `tests/test_twitch_api.py`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_twitch_api.py
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
        # Use the real httpx exception type so except clauses match correctly
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
        # Should not raise, just log error
        await api.send_message("fail")
    assert mock_http.post.await_count == 2
    # Refresh was attempted exactly once before the second try
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
    # Only one attempt — no retry after failed refresh
    assert mock_http.post.await_count == 1
```

- [ ] **Step 2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_api.py -v 2>&1 | head -15
```
Attendu : `ModuleNotFoundError: No module named 'bot.twitch.api'`

- [ ] **Step 3 : Implémenter `bot/twitch/api.py`**

```python
# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager


class TwitchAPI:
    MESSAGES_URL = "https://api.twitch.tv/helix/chat/messages"

    def __init__(
        self,
        token_manager: "TwitchTokenManager",
        client_id: str,
        bot_id: str,
        broadcaster_id: str,
    ):
        self._tm = token_manager
        self._client_id = client_id
        self._bot_id = bot_id
        self._broadcaster_id = broadcaster_id

    async def send_message(self, text: str) -> None:
        """POST /helix/chat/messages. Retry once on 401 after bot token refresh."""
        for attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self.MESSAGES_URL,
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        json={
                            "broadcaster_id": self._broadcaster_id,
                            "sender_id": self._bot_id,
                            "message": text,
                        },
                        timeout=10,
                    )
                if resp.status_code == 401:
                    if attempt == 0:
                        logger.warning(
                            "Twitch chat API 401 — refreshing bot token and retrying"
                        )
                        refreshed = await self._tm.refresh("bot")
                        if not refreshed:
                            logger.error(
                                "Bot token refresh failed, cannot send message"
                            )
                            return
                        continue
                    logger.error("Twitch chat API 401 after refresh, giving up")
                    return
                resp.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                logger.error("Twitch send_message HTTP error: {e}", e=exc)
                return
            except Exception as exc:
                logger.error("Twitch send_message error: {e}", e=exc)
                return
```

- [ ] **Step 4 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_api.py -v
```
Attendu : tous les tests PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/twitch/api.py tests/test_twitch_api.py
git commit -m "feat: add TwitchAPI.send_message with 401 retry via TwitchTokenManager"
```

---

## Chunk 3 : handlers.py — payload EventSub

### Task 3: Adapter handle_message pour le payload EventSub

**Files:**
- Modify: `bot/twitch/handlers.py`
- Modify: `tests/test_twitch_handlers.py`

- [ ] **Step 1 : Mettre à jour les tests**

Remplacer `make_message()` par `make_payload()`. Ajouter `twitch_api` au bot mock. Remplacer les assertions sur `message.channel.send` par `bot.twitch_api.send_message`.

```python
# tests/test_twitch_handlers.py  (remplacement complet)
"""
Tests for Twitch message handler pipeline.
Payload is an EventSub channel.chat.message object (not a twitchio IRC Message).
"""
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.twitch.handlers import handle_message, _post_process
from bot.twitch.events import _bits_joy


def make_bot(trigger_names=None, cooldown_seconds=10, trust=0.5):
    bot = MagicMock()
    bot.config.bot.trigger_names = trigger_names or ["wally"]
    bot.config.bot.language_default = "fr"
    bot.config.twitch.cooldown_seconds = cooldown_seconds

    bot._cooldowns = {}
    bot.is_on_cooldown = lambda user_id: (
        time.time() - bot._cooldowns.get(user_id, 0.0)
    ) < cooldown_seconds

    def set_cooldown(user_id):
        bot._cooldowns[user_id] = time.time()

    bot.set_cooldown = set_cooldown

    bot.db.get_trust_score = AsyncMock(return_value=trust)
    bot.db.update_trust_score = AsyncMock()

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.3, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    )
    bot.emotion.process_message = AsyncMock()

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()

    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.openai.complete = AsyncMock(return_value="Salut depuis Twitch!")

    # TwitchAPI (remplace IRC channel.send)
    bot.twitch_api.send_message = AsyncMock()

    return bot


def make_payload(content="wally salut", author_name="streamer",
                 author_id="111", channel="mychannel"):
    payload = MagicMock()
    payload.message.text = content
    payload.chatter.name = author_name
    payload.chatter.id = author_id
    payload.broadcaster.name = channel
    return payload


# ── handle_message ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ignores_untriggered_messages(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    payload = make_payload(content="hello friend")
    await handle_message(bot, payload)
    bot.openai.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_by_name_sends_reply(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=["wally"])
    payload = make_payload(content="wally qui es-tu?")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    bot.twitch_api.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_by_mention_sends_reply(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(trigger_names=[])
    payload = make_payload(content="@wallybot réponds!")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    bot.twitch_api.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_cooldown_prevents_second_response(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(cooldown_seconds=60)
    bot._cooldowns["111"] = time.time()
    payload = make_payload(content="wally salut")
    await handle_message(bot, payload)
    bot.openai.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_truncated_at_480(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    bot.openai.complete = AsyncMock(return_value="x" * 600)
    payload = make_payload(content="wally parle")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    sent_text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert len(sent_text) <= 480
    assert sent_text.endswith("...")


@pytest.mark.asyncio
async def test_appends_to_context_window(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot()
    payload = make_payload(content="wally test", author_name="bob", author_id="42")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    assert bot.memory.append_message.call_count == 2
    calls = bot.memory.append_message.call_args_list
    assert calls[0].args[1] == "bob"
    assert calls[1].args[1] == "Wally"


@pytest.mark.asyncio
async def test_sets_cooldown_after_response(monkeypatch):
    monkeypatch.setenv("TWITCH_BOT_NICK", "wallybot")
    bot = make_bot(cooldown_seconds=10)
    payload = make_payload(content="wally bonjour", author_id="789")
    with patch("bot.twitch.handlers.asyncio.create_task"):
        await handle_message(bot, payload)
    assert "789" in bot._cooldowns


# ── _post_process ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_process_calls_emotion_and_trust():
    bot = make_bot()
    await _post_process(bot, "merci wally", "twitch", "111", 0.5)
    bot.emotion.process_message.assert_awaited_once_with("merci wally", trust_score=0.5)
    bot.db.update_trust_score.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_process_decreases_trust_on_insult():
    bot = make_bot()
    await _post_process(bot, "tu es un idiot", "twitch", "111", 0.5)
    call = bot.db.update_trust_score.call_args
    assert call.args[2] < 0


# ── _bits_joy ─────────────────────────────────────────────────────────────────

def test_bits_joy_small():
    assert _bits_joy(50) == 0.1


def test_bits_joy_medium():
    assert _bits_joy(100) == 0.3
    assert _bits_joy(500) == 0.3


def test_bits_joy_large():
    assert _bits_joy(1000) == 0.6
    assert _bits_joy(9999) == 0.6
```

- [ ] **Step 2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py -v 2>&1 | head -20
```
Attendu : échecs sur `test_trigger_by_name_sends_reply` etc. (IRC vs API)

- [ ] **Step 3 : Mettre à jour `bot/twitch/handlers.py`**

```python
# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def handle_message(bot: "WallyTwitch", payload) -> None:
    """Handle an incoming channel.chat.message EventSub payload."""
    content: str = payload.message.text
    content_lower = content.lower()
    author: str = payload.chatter.name
    user_id: str = str(payload.chatter.id)

    # Trigger check: @botnick (from TWITCH_BOT_NICK env) or any configured trigger name.
    # bot.nick is unreliable without an IRC connection, so we read the env var directly.
    bot_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
    triggered = (bot_nick and f"@{bot_nick}" in content_lower) or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    if bot.is_on_cooldown(user_id):
        return

    try:
        platform = "twitch"
        trust = await bot.db.get_trust_score(platform, user_id)
        channel_name: str = payload.broadcaster.name

        mem_context = await bot.memory.search(platform, user_id, content)
        channel_id = f"twitch:{channel_name}"
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        situation = {
            "platform": "Twitch",
            "streamer": channel_name,
            "channel": f"#{channel_name}",
        }
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
        )
        context_block = bot.prompts.build_context_block(context_msgs)
        user_content = (
            context_block + f"\n[{author}]: {content}" if context_block else content
        )

        reply = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_response",
        )

        if len(reply) > 480:
            reply = reply[:477] + "..."

        await bot.twitch_api.send_message(text=reply)
        bot.set_cooldown(user_id)

        bot.memory.append_message(channel_id, author, content)
        bot.memory.append_message(channel_id, "Wally", reply)

        _fire(_post_process(bot, content, platform, user_id, trust))

    except Exception as e:
        logger.error("Twitch message handling error: {e}", e=e)


async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
    trust: float,
) -> None:
    try:
        await bot.emotion.process_message(text, trust_score=trust)
        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)
```

- [ ] **Step 4 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_handlers.py -v
```
Attendu : tous les tests PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/twitch/handlers.py tests/test_twitch_handlers.py
git commit -m "feat: adapt handle_message to EventSub payload, send via TwitchAPI"
```

---

## Chunk 4 : events.py — nouveaux handlers + patch twitchio

### Task 4: Mettre à jour events.py et ajouter les tests

**Files:**
- Modify: `bot/twitch/events.py`
- Create: `tests/test_twitch_events.py`

**Contexte twitchio :** `channel.chat.message` est absent de `SubscriptionTypes` dans twitchio v2. On le patch au runtime avant de créer les subscriptions. La `ChatMessageData` est définie dans `events.py`.

**Rappel payload `channel.subscription.gift` :** `payload.total` = nb de gifts dans la transaction. `payload.cumulative_total` = total historique du gifter (non utilisé dans le message).

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_twitch_events.py
"""Tests for Twitch EventSub event handlers."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.twitch.events import (
    _bits_joy,
    register_events,
)


def make_bot(event_cfg=None):
    bot = MagicMock()
    bot.emotion.apply_delta = MagicMock()
    bot.emotion.get_state = MagicMock(return_value={})
    bot.prompts.build_system_prompt = MagicMock(return_value="sys")
    bot.openai.complete = AsyncMock(return_value="réponse")
    bot.twitch_api.send_message = AsyncMock()

    default_cfg = {
        "follow": MagicMock(active=True, message="follow {username}"),
        "sub": MagicMock(active=True, message="sub {username}"),
        "resub": MagicMock(active=True, message="resub {username} {months}"),
        "gift_sub": MagicMock(active=True, message="gift {username} x{amount}"),
        "bits": MagicMock(active=True, message="bits {username} {amount}"),
        "raid": MagicMock(active=True, message="raid {username} {raiders_count}"),
    }
    if event_cfg:
        default_cfg.update(event_cfg)
    bot.config.twitch_events.get = lambda k, d=None: default_cfg.get(k, d)
    return bot


def make_gift_payload(gifter="alice", total=5, cumulative=20, is_anonymous=False,
                      broadcaster="mychan"):
    payload = MagicMock()
    payload.is_anonymous = is_anonymous
    payload.user.name = gifter
    payload.total = total
    payload.cumulative_total = cumulative
    payload.broadcaster.name = broadcaster
    return payload


def make_sub_end_payload(username="bob", broadcaster="mychan"):
    payload = MagicMock()
    payload.user.name = username
    payload.broadcaster.name = broadcaster
    return payload


def make_chat_payload(content="wally salut", author_name="streamer",
                      author_id="111", channel="mychannel"):
    payload = MagicMock()
    payload.message.text = content
    payload.chatter.name = author_name
    payload.chatter.id = author_id
    payload.broadcaster.name = channel
    return payload


# ── gift sub handler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gift_sub_applies_joy_delta():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))

    register_events(bot)
    handler = handlers.get("event_eventsub_notification_subscription_gift")
    assert handler is not None

    payload = make_gift_payload(total=5)
    with patch("bot.twitch.events._generate_and_send", new_callable=AsyncMock):
        await handler(payload)

    bot.emotion.apply_delta.assert_called_once_with("joy", 0.5)


@pytest.mark.asyncio
async def test_gift_sub_uses_payload_total_not_cumulative():
    """amount in template must use payload.total, not payload.cumulative_total."""
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    payload = make_gift_payload(total=3, cumulative=50)
    captured = {}

    async def fake_send(b, channel, template, **kwargs):
        captured.update(kwargs)

    with patch("bot.twitch.events._generate_and_send", side_effect=fake_send):
        await handler(payload)

    assert captured["amount"] == 3   # payload.total
    assert captured["amount"] != 50  # NOT payload.cumulative_total


@pytest.mark.asyncio
async def test_gift_sub_anonymous_uses_anonyme():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    payload = make_gift_payload(is_anonymous=True, total=1)
    captured = {}

    async def fake_send(b, channel, template, **kwargs):
        captured.update(kwargs)

    with patch("bot.twitch.events._generate_and_send", side_effect=fake_send):
        await handler(payload)

    assert captured["username"] == "Anonyme"


@pytest.mark.asyncio
async def test_gift_sub_inactive_skips():
    bot = make_bot(event_cfg={"gift_sub": MagicMock(active=False)})
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers["event_eventsub_notification_subscription_gift"]

    with patch("bot.twitch.events._generate_and_send", new_callable=AsyncMock) as mock_send:
        await handler(make_gift_payload())
    mock_send.assert_not_awaited()


# ── subscription end handler ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_end_no_message_sent():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers.get("event_eventsub_notification_subscription_end")
    assert handler is not None

    payload = make_sub_end_payload()
    with patch("bot.twitch.events._generate_and_send", new_callable=AsyncMock) as mock_send:
        await handler(payload)
    mock_send.assert_not_awaited()
    bot.twitch_api.send_message.assert_not_awaited()


# ── channel.chat.message handler ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_message_handler_calls_handle_message():
    bot = make_bot()
    handlers = {}
    bot.event = lambda: (lambda fn: handlers.__setitem__(fn.__name__, fn))
    register_events(bot)
    handler = handlers.get("event_eventsub_notification_channel_chat_message")
    assert handler is not None

    payload = make_chat_payload(content="wally salut")
    with patch("bot.twitch.events.handle_message", new_callable=AsyncMock) as mock_handle:
        await handler(payload)
    mock_handle.assert_awaited_once_with(bot, payload)


# ── _generate_and_send uses TwitchAPI ────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_and_send_uses_twitch_api():
    """_generate_and_send must call bot.twitch_api.send_message, not IRC channel.send."""
    from bot.twitch.events import _generate_and_send

    bot = make_bot()
    bot.get_channel = MagicMock(return_value=None)  # no IRC channel

    await _generate_and_send(bot, "mychan", "Bonjour {username}!", username="alice",
                              amount=0, months=0, raiders_count=0)

    bot.twitch_api.send_message.assert_awaited_once()
    sent = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "alice" in sent


# ── SubscriptionTypes patch + _subscribe_chat ─────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_chat_patches_subscription_types():
    """start_eventsub_client() must patch SubscriptionTypes before any subscription."""
    from twitchio.ext.eventsub.models import SubscriptionTypes

    # Remove any prior patch to test from clean state
    SubscriptionTypes._name_map.pop("channel.chat.message", None)
    SubscriptionTypes._type_map.pop("channel.chat.message", None)

    bot = make_bot()
    with patch("bot.twitch.events.os.getenv", side_effect=lambda k, d="": {
        "TWITCH_BROADCASTER_ID": "bc123",
        "TWITCH_BOT_ID": "bot456",
    }.get(k, d)):
        bot.token_manager = MagicMock()
        bot.token_manager.bot_token = "bt"
        bot.token_manager.streamer_token = ""
        with patch("twitchio.ext.eventsub.EventSubWSClient") as MockWSClient:
            mock_client = MockWSClient.return_value
            mock_client.subscribe_channel_follows_v2 = AsyncMock()
            mock_client.subscribe_channel_raid = AsyncMock()
            mock_client._assign_subscription = AsyncMock()
            mock_client.subscribe_channel_subscriptions = AsyncMock()
            mock_client.subscribe_channel_subscription_messages = AsyncMock()
            mock_client.subscribe_channel_subscription_gifts = AsyncMock()
            mock_client.subscribe_channel_subscription_end = AsyncMock()
            mock_client.subscribe_channel_cheers = AsyncMock()
            from bot.twitch.events import start_eventsub_client
            await start_eventsub_client(bot)

    assert "channel.chat.message" in SubscriptionTypes._name_map
    assert SubscriptionTypes._name_map["channel.chat.message"] == "channel_chat_message"
    from bot.twitch.events import ChatMessageData
    assert SubscriptionTypes._type_map["channel.chat.message"] is ChatMessageData


@pytest.mark.asyncio
async def test_subscribe_chat_calls_assign_subscription():
    """_subscribe_chat must call client._assign_subscription with correct condition."""
    from bot.twitch.events import _subscribe_chat, ChatMessageData

    mock_client = MagicMock()
    mock_client._assign_subscription = AsyncMock()

    await _subscribe_chat(mock_client, "bc123", "bot456", "bot_token")

    mock_client._assign_subscription.assert_awaited_once()
    sub = mock_client._assign_subscription.call_args.args[0]
    assert sub.condition == {"broadcaster_user_id": "bc123", "user_id": "bot456"}
    assert sub.token == "bot_token"
    assert sub.event[2] is ChatMessageData
```

- [ ] **Step 2 : Lancer les tests — vérifier qu'ils échouent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_events.py -v 2>&1 | head -25
```
Attendu : échecs sur handlers gift_sub, subscription_end, chat_message absents + `_generate_and_send` utilise encore IRC

- [ ] **Step 3 : Mettre à jour `bot/twitch/events.py`**

```python
# bot/twitch/events.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _bits_joy(amount: int) -> float:
    """Map bits amount to joy delta per the design spec."""
    if amount >= 1000:
        return 0.6
    if amount >= 100:
        return 0.3
    return 0.1


async def _generate_and_send(
    bot: "WallyTwitch",
    channel_name: str,
    template: str,
    **kwargs,
) -> None:
    """Generate an OpenAI response from an event template and send via Helix API."""
    try:
        from bot.core.prompts import PromptBuilder

        formatted = PromptBuilder.format_event_message(template, **kwargs)
        situation = {"platform": "Twitch", "streamer": channel_name}
        system = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
        )
        reply = await bot.openai.complete(
            system,
            [{"role": "user", "content": f"Réagis à cet événement Twitch : {formatted}"}],
            purpose="twitch_event",
        )
        if len(reply) > 480:
            reply = reply[:477] + "..."
        await bot.twitch_api.send_message(text=reply)
    except Exception as e:
        logger.error("Twitch event send error: {e}", e=e)


def register_events(bot: "WallyTwitch") -> None:
    """Register EventSub WebSocket event handlers on the bot instance."""

    @bot.event()
    async def event_eventsub_notification_followV2(payload) -> None:
        cfg = bot.config.twitch_events.get("follow")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.1)
        await _generate_and_send(
            bot, payload.broadcaster.name, cfg.message,
            username=payload.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription(payload) -> None:
        cfg = bot.config.twitch_events.get("sub")
        if not cfg or not cfg.active:
            return
        if payload.is_gift:
            return  # gift subs handled by subscription_gift handler
        bot.emotion.apply_delta("joy", 0.4)
        await _generate_and_send(
            bot, payload.broadcaster.name, cfg.message,
            username=payload.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_message(payload) -> None:
        cfg = bot.config.twitch_events.get("resub")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.3)
        await _generate_and_send(
            bot, payload.broadcaster.name, cfg.message,
            username=payload.user.name, amount=0,
            months=payload.cumulative_months, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_gift(payload) -> None:
        cfg = bot.config.twitch_events.get("gift_sub")
        if not cfg or not cfg.active:
            return
        bot.emotion.apply_delta("joy", 0.5)
        gifter = "Anonyme" if payload.is_anonymous else payload.user.name
        await _generate_and_send(
            bot, payload.broadcaster.name, cfg.message,
            username=gifter,
            amount=payload.total,   # nb de gifts dans cette transaction
            months=0,
            raiders_count=0,
        )
        # payload.cumulative_total disponible pour un futur template "X gifts au total"

    @bot.event()
    async def event_eventsub_notification_subscription_end(payload) -> None:
        logger.debug("Sub end: {user}", user=payload.user.name)
        # Pas de réaction visible dans le chat

    @bot.event()
    async def event_eventsub_notification_cheer(payload) -> None:
        cfg = bot.config.twitch_events.get("bits")
        if not cfg or not cfg.active:
            return
        delta = _bits_joy(payload.bits)
        bot.emotion.apply_delta("joy", delta)
        username = "Anonyme" if payload.is_anonymous else payload.user.name
        await _generate_and_send(
            bot, payload.broadcaster.name, cfg.message,
            username=username, amount=payload.bits, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_raid(payload) -> None:
        cfg = bot.config.twitch_events.get("raid")
        if not cfg or not cfg.active:
            return
        joy_spike = min(payload.viewer_count / 50, 0.9)
        bot.emotion.apply_delta("joy", joy_spike)
        # Note: twitchio v2 uses .reciever (typo in library — missing second 'e')
        channel_name = payload.reciever.name
        await _generate_and_send(
            bot, channel_name, cfg.message,
            username=payload.raider.name, amount=0,
            months=0, raiders_count=payload.viewer_count,
        )

    @bot.event()
    async def event_eventsub_notification_channel_chat_message(payload) -> None:
        from bot.twitch.handlers import handle_message
        await handle_message(bot, payload)


class ChatMessageData:
    """Minimal data model for channel.chat.message EventSub notifications.

    Registered into twitchio v2's SubscriptionTypes at runtime in
    start_eventsub_client() since twitchio v2 does not natively support
    channel.chat.message.

    Attributes match the EventSub payload field names:
      chatter.id    — chatter_user_id
      chatter.name  — chatter_user_login
      message.text  — message.text
      broadcaster.name — broadcaster_user_login
    """

    __slots__ = "chatter", "message", "broadcaster"

    def __init__(self, client, data: dict):
        # Use twitchio's create_user to get PartialUser objects
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )


class _ChatMessageText:
    __slots__ = ("text",)

    def __init__(self, data: dict):
        self.text: str = data["text"]


async def start_eventsub_client(bot: "WallyTwitch") -> None:
    """Create an EventSub WebSocket client and subscribe to channel events.

    Patches twitchio v2's SubscriptionTypes at runtime to add
    channel.chat.message support (absent from twitchio v2 natively).

    Token usage:
      Bot token  (BOT_ACCESS_TOKEN):
        channel.follow v2  — moderator:read:followers
        channel.raid       — (no scope)
        channel.chat.message — user:read:chat

      Streamer token (STREAMER_ACCESS_TOKEN):
        channel.subscribe, channel.subscription.message,
        channel.subscription.gift, channel.subscription.end — channel:read:subscriptions
        channel.cheer — bits:read
    """
    broadcaster_id = os.getenv("TWITCH_BROADCASTER_ID", "").strip()
    bot_id = os.getenv("TWITCH_BOT_ID", "").strip() or broadcaster_id
    bot_token = bot.token_manager.bot_token
    streamer_token = bot.token_manager.streamer_token

    if not broadcaster_id or not bot_token:
        logger.warning(
            "EventSub skipped — TWITCH_BROADCASTER_ID and BOT_ACCESS_TOKEN required"
        )
        return

    try:
        from twitchio.ext import eventsub
        from twitchio.ext.eventsub.models import SubscriptionTypes
        from twitchio.ext.eventsub.websocket import _Subscription

        # Patch twitchio v2 to support channel.chat.message
        # (absent from SubscriptionTypes — would cause KeyError in pump() if not patched)
        if "channel.chat.message" not in SubscriptionTypes._name_map:
            SubscriptionTypes._name_map["channel.chat.message"] = "channel_chat_message"
            SubscriptionTypes._type_map["channel.chat.message"] = ChatMessageData

        client = eventsub.EventSubWSClient(bot)

        # Subscriptions are awaited sequentially — see existing code comment re: 4003 errors.
        subscriptions: list[tuple[str, object]] = [
            ("follow", client.subscribe_channel_follows_v2(
                broadcaster=broadcaster_id, moderator=bot_id, token=bot_token
            )),
            ("raid", client.subscribe_channel_raid(
                token=bot_token, to_broadcaster=broadcaster_id
            )),
            ("chat", _subscribe_chat(client, broadcaster_id, bot_id, bot_token)),
        ]

        if streamer_token:
            subscriptions += [
                ("sub", client.subscribe_channel_subscriptions(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("resub", client.subscribe_channel_subscription_messages(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("gift_sub", client.subscribe_channel_subscription_gifts(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("subscription_end", client.subscribe_channel_subscription_end(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
                ("cheer", client.subscribe_channel_cheers(
                    broadcaster=broadcaster_id, token=streamer_token
                )),
            ]
        else:
            logger.warning(
                "EventSub: streamer subscriptions skipped — set STREAMER_ACCESS_TOKEN "
                "(channel:read:subscriptions, bits:read)"
            )

        for name, coro in subscriptions:
            try:
                await coro
                logger.info("EventSub subscribed: {sub}", sub=name)
            except Exception as exc:
                logger.warning(
                    "EventSub subscription failed [{sub}]: {e}", sub=name, e=exc
                )

        bot._eventsub_client = client
        logger.info(
            "EventSub WebSocket client active (broadcaster_id={bid})", bid=broadcaster_id
        )

    except Exception as exc:
        logger.error("EventSub client setup failed: {e}", e=exc)


async def _subscribe_chat(client, broadcaster_id: str, bot_id: str, token: str):
    """Subscribe to channel.chat.message via manual _Subscription (not in twitchio v2 API).

    Uses EventSubWSClient._assign_subscription() — the same internal path used by all
    native subscribe_* methods (e.g. subscribe_channel_follows_v2). add_subscription()
    and _wakeup_and_connect() are methods on the inner Websocket class, not on
    EventSubWSClient — using them directly would raise AttributeError.
    """
    from twitchio.ext.eventsub.websocket import _Subscription

    sub = _Subscription(
        ("channel.chat.message", 1, ChatMessageData),
        {"broadcaster_user_id": broadcaster_id, "user_id": bot_id},
        token,
    )
    await client._assign_subscription(sub)
```

- [ ] **Step 4 : Lancer les tests — vérifier qu'ils passent**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_events.py -v
```
Attendu : tous les tests PASS

- [ ] **Step 5 : Commit**

```bash
git add bot/twitch/events.py tests/test_twitch_events.py
git commit -m "feat: add gift_sub/sub_end handlers, channel.chat.message via twitchio patch, Helix send"
```

---

## Chunk 5 : bot.py + main.py + config

### Task 5: Mettre à jour bot.py, main.py, .env.example, config.yaml

**Files:**
- Modify: `bot/twitch/bot.py`
- Modify: `bot/main.py`
- Modify: `.env.example`
- Modify: `config.yaml`

Pas de nouveaux tests unitaires pour bot.py et main.py (comportement couvert par les tests d'intégration des composants). Les changements sont du câblage DI.

- [ ] **Step 1 : Mettre à jour `bot/twitch/bot.py`**

```python
# bot/twitch/bot.py
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.openai_client import OpenAIClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI


class WallyTwitch(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        openai: "OpenAIClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        token_manager: "TwitchTokenManager",
        twitch_api: "TwitchAPI",
    ):
        super().__init__(
            token=token_manager.bot_token,
            prefix="!",
            initial_channels=[],  # No IRC connection — chat is handled via EventSub
        )
        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.openai = openai
        self.prompts = prompts
        self.language = language
        self.token_manager = token_manager
        self.twitch_api = twitch_api
        # Per-user cooldown: {user_id: last_response_timestamp}
        self._cooldowns: dict[str, float] = {}

    def is_on_cooldown(self, user_id: str) -> bool:
        last = self._cooldowns.get(user_id, 0.0)
        return (time.time() - last) < self.config.twitch.cooldown_seconds

    def set_cooldown(self, user_id: str) -> None:
        self._cooldowns[user_id] = time.time()

    async def event_token_expired(self) -> Optional[str]:
        """Called by twitchio when the IRC/API OAuth token expires."""
        refreshed = await self.token_manager.refresh("bot")
        if refreshed:
            return self.token_manager.bot_token
        return None

    async def event_ready(self) -> None:
        logger.info("Twitch bot ready as {nick}", nick=self.nick)
        from bot.twitch.events import start_eventsub_client
        await start_eventsub_client(self)

    async def event_error(self, error: Exception, data=None) -> None:
        logger.error("Twitch error: {e}", e=error)
```

- [ ] **Step 2 : Mettre à jour `bot/main.py`**

Supprimer `_resolve_twitch_token()`. Ajouter `TwitchTokenManager` et `TwitchAPI` dans le bloc d'initialisation Twitch.

```python
# Dans bot/main.py — remplacer le bloc Twitch (lignes ~123-140) par :

    # ── Twitch adapter ────────────────────────────────────────────────────────
    from bot.twitch.bot import WallyTwitch
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.twitch.events import register_events

    env_path = Path(__file__).parent.parent / ".env"
    token_manager = TwitchTokenManager.load(env_path)
    await token_manager.startup_validate()

    discord_token = os.getenv("DISCORD_TOKEN", "")

    tasks = [discord_bot.start(discord_token)]
    if token_manager.bot_token:
        twitch_api = TwitchAPI(
            token_manager=token_manager,
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            bot_id=os.getenv("TWITCH_BOT_ID", ""),
            broadcaster_id=os.getenv("TWITCH_BROADCASTER_ID", ""),
        )
        twitch_bot = WallyTwitch(
            config, db, emotion, memory, openai_client, prompts, language,
            token_manager=token_manager,
            twitch_api=twitch_api,
        )
        register_events(twitch_bot)
        tasks.append(twitch_bot.start())
        logger.info("Twitch adapter configured and included in gather")
    else:
        logger.warning(
            "Twitch bot skipped — set BOT_ACCESS_TOKEN (or BOT_REFRESH_TOKEN + "
            "TWITCH_CLIENT_ID/SECRET) to enable"
        )
```

Ajouter `from pathlib import Path` en tête de `bot/main.py` (dans les imports existants). Supprimer la fonction `_resolve_twitch_token()` (lignes 24-57).

- [ ] **Step 3 : Vérifier que main.py est correct**

```bash
cd /opt/stacks/wally-ai && python -c "import ast; ast.parse(open('bot/main.py').read()); print('OK')"
```
Attendu : `OK`

- [ ] **Step 4 : Mettre à jour `.env.example`**

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Discord
DISCORD_TOKEN=
DISCORD_GUILD_ID=

# Twitch — identifiants OAuth
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=

# IDs numériques
TWITCH_BROADCASTER_ID=
TWITCH_BOT_ID=
TWITCH_BOT_NICK=wallybot

# Token du compte bot (scopes: user:read:chat user:write:chat user:bot moderator:read:followers)
BOT_ACCESS_TOKEN=
BOT_REFRESH_TOKEN=

# Token du compte streamer (scopes: bits:read channel:read:subscriptions)
STREAMER_ACCESS_TOKEN=
STREAMER_REFRESH_TOKEN=

# Qdrant (internal Docker network)
QDRANT_URL=http://qdrant:6333

# Database path (inside container)
DB_PATH=data/wally.db
```

- [ ] **Step 5 : Mettre à jour `config.yaml` — ajouter gift_sub**

Ajouter dans la section `twitch_events` :
```yaml
  gift_sub:
    active: false
    message: "{username} vient d'offrir {amount} sub(s) ! Merci pour ta générosité !"
```

- [ ] **Step 6 : Lancer la suite de tests complète**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Attendu : tous les tests PASS (110+ tests)

- [ ] **Step 7 : Commit final**

```bash
git add bot/twitch/bot.py bot/main.py .env.example config.yaml
git commit -m "feat: wire TwitchTokenManager + TwitchAPI in bot.py and main.py, remove IRC"
```
