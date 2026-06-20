# Wally V2 Plan C — Autonomy Advanced Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Wally the ability to fix its own code and self-upgrade, both gated by owner Discord reaction approval via a host-side bridge daemon.

**Architecture:** A host-side HTTP daemon (`host_bridge_daemon.py`) listens on a Unix socket at `/opt/stacks/wally-ai/data/bridge.sock`, which is visible inside the container at `/app/data/bridge.sock` (via the existing `./data:/app/data` volume mount). The bot calls the bridge over httpx with a shared secret header. `SelfFix` generates a unified diff via LLM, DMs the owner a preview, and on ✅ reaction calls bridge `/git-apply` then `/docker-rebuild`. `SelfUpgrade` monitors UpdateChecker and on new version DMs owner; ✅ triggers bridge `/docker-restart`. A standalone `watchdog.py` script runs on the host and restarts the bot via `docker compose up` after 3 consecutive health-check failures.

**Tech Stack:** Python 3.11+, `httpx` (UDS transport), `http.server` + `socketserver.UnixStreamServer` (stdlib), `discord.py` `wait_for` reaction gates, `asyncio.create_task`, `subprocess.Popen(shell=True, start_new_session=True)`, `pytest-asyncio`.

## Global Constraints

- `OWNER_DISCORD_ID = "610550333042589752"` — hardcoded constant, never read from config
- Bridge socket host path: `/opt/stacks/wally-ai/data/bridge.sock`
- Bridge socket container path: `/app/data/bridge.sock` (same physical file via volume)
- `BRIDGE_SECRET`: from `BRIDGE_SECRET` env var — never hardcoded
- `ALLOWED_SERVICES = {"wally"}` — whitelist in daemon; any other service name → 400
- `git apply --check` dry-run MUST run and succeed before the real `git apply`
- docker-rebuild uses `shell=True`: `f"docker compose -f {COMPOSE_FILE} build {svc} && docker compose -f {COMPOSE_FILE} up -d --force-recreate {svc}"`
- docker-restart uses `shell=True`: `f"docker compose -f {COMPOSE_FILE} up -d --force-recreate {svc}"`
- Both docker commands use `subprocess.Popen(..., shell=True, start_new_session=True)` so the HTTP response returns before the container dies
- `code_fix` owner double-check: enforced in `ActionDispatcher._act` (requester_id check) AND in `SelfFix.fix` (redundant guard)
- `SelfUpgrade` reaction timeout: `86400` seconds (24h)
- `SelfFix` reaction timeout: `3600` seconds (1h)
- Watchdog `FAIL_THRESHOLD = 3` consecutive failures before restart
- Watchdog `CHECK_INTERVAL = 60` seconds
- `bot.self_fix = None` and `bot.self_upgrade = None` in `WallyDiscord.__init__` (V1 test compat)
- All V1 handler test mocks that set `bot.response_gate = None` must also set `bot.self_fix = None` and `bot.self_upgrade = None`

---

### Task 13: HostBridgeDaemon + HostBridgeClient

**Files:**
- Create: `scripts/host_bridge_daemon.py`
- Create: `wally_v2/core/host_bridge.py`
- Create: `tests/v2/core/test_host_bridge.py`

**Interfaces:**
- Produces:
  - `HostBridgeClient(socket_path: str, secret: str)`
  - `async def health(self) -> bool`
  - `async def git_apply(self, diff: str) -> None` — raises `HostBridgeError` on failure
  - `async def docker_rebuild(self, service: str = "wally") -> None` — raises `HostBridgeError`
  - `async def docker_restart(self, service: str = "wally") -> None` — raises `HostBridgeError`
  - `class HostBridgeError(Exception)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/v2/core/test_host_bridge.py
import json
import pytest
import httpx
from unittest.mock import patch

from wally_v2.core.host_bridge import HostBridgeClient, HostBridgeError


def make_transport(responses: dict):
    """responses: {"GET /health": (200, {...}), "POST /git-apply": (200, {...}), ...}"""
    def handler(request):
        key = f"{request.method} {request.url.path}"
        if key in responses:
            code, body = responses[key]
            return httpx.Response(code, json=body)
        return httpx.Response(404, json={"error": "not found"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_health_returns_true_on_200():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"GET /health": (200, {"status": "ok"})})
    with patch.object(client, "_transport", return_value=transport):
        assert await client.health() is True


@pytest.mark.asyncio
async def test_health_returns_false_on_connection_error():
    client = HostBridgeClient("/tmp/nonexistent.sock", "secret")
    # No patch — real UDS connect will fail
    result = await client.health()
    assert result is False


@pytest.mark.asyncio
async def test_git_apply_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /git-apply": (200, {"status": "applied"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.git_apply("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")


@pytest.mark.asyncio
async def test_git_apply_raises_on_error():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /git-apply": (400, {"error": "patch does not apply"})})
    with patch.object(client, "_transport", return_value=transport):
        with pytest.raises(HostBridgeError, match="patch does not apply"):
            await client.git_apply("bad diff")


@pytest.mark.asyncio
async def test_docker_restart_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /docker-restart": (200, {"status": "restarting"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.docker_restart("wally")


@pytest.mark.asyncio
async def test_docker_rebuild_success():
    client = HostBridgeClient("/tmp/test.sock", "secret")
    transport = make_transport({"POST /docker-rebuild": (200, {"status": "rebuilding"})})
    with patch.object(client, "_transport", return_value=transport):
        await client.docker_rebuild("wally")
```

- [ ] **Step 2: Run tests — expect ImportError**

```
python3 -m pytest tests/v2/core/test_host_bridge.py -v
```
Expected: `ImportError: cannot import name 'HostBridgeClient'`

- [ ] **Step 3: Write `wally_v2/core/host_bridge.py`**

```python
from __future__ import annotations

import httpx
from loguru import logger


class HostBridgeError(Exception):
    pass


class HostBridgeClient:
    def __init__(self, socket_path: str, secret: str) -> None:
        self._socket_path = socket_path
        self._secret = secret

    def _transport(self) -> httpx.AsyncHTTPTransport:
        return httpx.AsyncHTTPTransport(uds=self._socket_path)

    def _headers(self) -> dict[str, str]:
        return {"X-Bridge-Secret": self._secret}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(transport=self._transport(), timeout=5.0) as c:
                r = await c.get("http://bridge/health")
                return r.status_code == 200
        except Exception as e:
            logger.warning("HostBridge health failed: {}", e)
            return False

    async def git_apply(self, diff: str) -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=30.0) as c:
            r = await c.post(
                "http://bridge/git-apply",
                json={"diff": diff},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))

    async def docker_rebuild(self, service: str = "wally") -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=10.0) as c:
            r = await c.post(
                "http://bridge/docker-rebuild",
                json={"service": service},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))

    async def docker_restart(self, service: str = "wally") -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=10.0) as c:
            r = await c.post(
                "http://bridge/docker-restart",
                json={"service": service},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))
```

- [ ] **Step 4: Write `scripts/host_bridge_daemon.py`**

```python
#!/usr/bin/env python3
"""Host-side bridge daemon. Listens on a Unix socket, exposes whitelisted Docker/git operations."""
import http.server
import json
import logging
import os
import socketserver
import subprocess
from pathlib import Path

SOCKET_PATH = os.environ.get("BRIDGE_SOCKET", "/opt/stacks/wally-ai/data/bridge.sock")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")
REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/opt/stacks/wally-ai"))
COMPOSE_FILE = str(REPO_ROOT / "docker-compose.yml")
ALLOWED_SERVICES: set[str] = {"wally"}


class BridgeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        logging.info(fmt, *args)

    def _auth(self) -> bool:
        return bool(BRIDGE_SECRET) and self.headers.get("X-Bridge-Secret") == BRIDGE_SECRET

    def _send(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._auth():
            self._send(401, {"error": "unauthorized"})
            return
        body = self._read_body()

        if self.path == "/git-apply":
            diff = body.get("diff", "")
            r = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=diff.encode(),
                cwd=REPO_ROOT,
                capture_output=True,
                timeout=30,
            )
            if r.returncode != 0:
                self._send(400, {"error": r.stderr.decode()})
                return
            subprocess.run(
                ["git", "apply", "-"],
                input=diff.encode(),
                cwd=REPO_ROOT,
                check=True,
                timeout=30,
            )
            self._send(200, {"status": "applied"})

        elif self.path == "/docker-rebuild":
            svc = body.get("service", "wally")
            if svc not in ALLOWED_SERVICES:
                self._send(400, {"error": "service not allowed"})
                return
            cmd = f"docker compose -f {COMPOSE_FILE} build {svc} && docker compose -f {COMPOSE_FILE} up -d --force-recreate {svc}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            self._send(200, {"status": "rebuilding"})

        elif self.path == "/docker-restart":
            svc = body.get("service", "wally")
            if svc not in ALLOWED_SERVICES:
                self._send(400, {"error": "service not allowed"})
                return
            cmd = f"docker compose -f {COMPOSE_FILE} up -d --force-recreate {svc}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
            self._send(200, {"status": "restarting"})

        else:
            self._send(404, {"error": "not found"})


class UnixServer(socketserver.UnixStreamServer):
    def server_bind(self) -> None:
        sock = Path(SOCKET_PATH)
        if sock.exists():
            sock.unlink()
        super().server_bind()
        sock.chmod(0o660)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with UnixServer(SOCKET_PATH, BridgeHandler) as s:
        logging.info("Bridge daemon listening on %s", SOCKET_PATH)
        s.serve_forever()
```

- [ ] **Step 5: Run tests — expect all passing**

```
python3 -m pytest tests/v2/core/test_host_bridge.py -v
```
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add wally_v2/core/host_bridge.py scripts/host_bridge_daemon.py tests/v2/core/test_host_bridge.py
git commit -m "feat(v2/c): add HostBridgeDaemon + HostBridgeClient (Unix socket)"
```

---

### Task 14: SelfUpgrade

**Files:**
- Create: `wally_v2/core/self_upgrade.py`
- Create: `tests/v2/core/test_self_upgrade.py`

**Interfaces:**
- Consumes: `HostBridgeClient.docker_restart(service)`, `UpdateChecker.update_available` (bool property + setter)
- Produces:
  - `class SelfUpgrade`
  - `def __init__(self, update_checker, bridge, bot) -> None`
  - `def start(self) -> None`
  - `async def stop(self) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/v2/core/test_self_upgrade.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_upgrade(update_available=False):
    from wally_v2.core.self_upgrade import SelfUpgrade

    checker = MagicMock()
    checker.update_available = update_available

    bridge = MagicMock()
    bridge.docker_restart = AsyncMock()

    bot = MagicMock()
    owner = AsyncMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 123
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    return SelfUpgrade(checker, bridge, bot), checker, bridge, bot, dm, msg


@pytest.mark.asyncio
async def test_loop_calls_propose_when_update_available():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade(update_available=True)
    with patch.object(upgrade, "_propose", new_callable=AsyncMock) as mock_propose:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]
            with pytest.raises(asyncio.CancelledError):
                await upgrade._loop()
        mock_propose.assert_called_once()


@pytest.mark.asyncio
async def test_propose_restarts_on_checkmark():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = 610550333042589752
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await upgrade._propose()

    bridge.docker_restart.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_propose_ignores_on_cross():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = 610550333042589752
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await upgrade._propose()

    bridge.docker_restart.assert_not_called()
    assert checker.update_available is False


@pytest.mark.asyncio
async def test_propose_ignores_on_timeout():
    upgrade, checker, bridge, bot, dm, msg = make_upgrade()
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

    await upgrade._propose()

    bridge.docker_restart.assert_not_called()
    assert checker.update_available is False


@pytest.mark.asyncio
async def test_start_stop():
    upgrade, *_ = make_upgrade()
    upgrade.start()
    assert upgrade._task is not None
    await upgrade.stop()
    assert upgrade._task.cancelled() or upgrade._task.done()
```

- [ ] **Step 2: Run — expect ImportError**

```
python3 -m pytest tests/v2/core/test_self_upgrade.py -v
```
Expected: `ImportError: cannot import name 'SelfUpgrade'`

- [ ] **Step 3: Write `wally_v2/core/self_upgrade.py`**

```python
from __future__ import annotations

import asyncio

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"


class SelfUpgrade:
    def __init__(self, update_checker, bridge, bot) -> None:
        self._checker = update_checker
        self._bridge = bridge
        self._bot = bot
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            if self._checker.update_available:
                await self._propose()

    async def _propose(self) -> None:
        try:
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            msg = await dm.send(
                "🔄 **Mise à jour Wally disponible.**\n"
                "Réagis ✅ pour appliquer (restart ~30s), ❌ pour ignorer.\n"
                "_(Timeout 24h)_"
            )
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            emoji = await self._await_reaction(msg, timeout=86400)
            if emoji == "✅":
                await dm.send("⚡ Redémarrage en cours...")
                await self._bridge.docker_restart("wally")
            else:
                self._checker.update_available = False
                await dm.send("❌ Mise à jour ignorée.")
        except asyncio.TimeoutError:
            self._checker.update_available = False
        except Exception as e:
            logger.error("SelfUpgrade._propose failed: {}", e)

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
```

- [ ] **Step 4: Run — expect all passing**

```
python3 -m pytest tests/v2/core/test_self_upgrade.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add wally_v2/core/self_upgrade.py tests/v2/core/test_self_upgrade.py
git commit -m "feat(v2/c): add SelfUpgrade with reaction gate (24h timeout)"
```

---

### Task 15: SelfFix + wire ActionDispatcher

**Files:**
- Create: `wally_v2/core/self_fix.py`
- Modify: `wally_v2/core/action_dispatcher.py` — replace `code_fix` warning branch
- Create: `tests/v2/core/test_self_fix.py`

**Interfaces:**
- Consumes: `HostBridgeClient.git_apply(diff)`, `HostBridgeClient.docker_rebuild(service)`, `BaseLLMClient.complete(system, messages)`, `bot.wait_for("reaction_add", check, timeout)`
- Produces:
  - `@dataclass class FixRequest(requester_discord_id: str, file_path: str, description: str)`
  - `class SelfFix`
  - `async def fix(self, request: FixRequest) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/v2/core/test_self_fix.py
import asyncio
import pytest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


OWNER_ID = "610550333042589752"
NON_OWNER_ID = "999999999999"


def make_fix(tmp_path: Path, llm_diff: str = "--- a/x\n+++ b/x\n"):
    from wally_v2.core.self_fix import SelfFix, FixRequest

    # create a real file in tmp_path
    src = tmp_path / "bot" / "core" / "emotion.py"
    src.parent.mkdir(parents=True)
    src.write_text("# original\n")

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_diff)

    bridge = MagicMock()
    bridge.git_apply = AsyncMock()
    bridge.docker_rebuild = AsyncMock()

    bot = MagicMock()
    owner = AsyncMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 42
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    fixer = SelfFix(llm, bridge, bot, repo_root=str(tmp_path))
    req_owner = FixRequest(
        requester_discord_id=OWNER_ID,
        file_path="bot/core/emotion.py",
        description="fix the bug",
    )
    req_non_owner = FixRequest(
        requester_discord_id=NON_OWNER_ID,
        file_path="bot/core/emotion.py",
        description="fix",
    )
    return fixer, bridge, llm, dm, msg, bot, req_owner, req_non_owner


@pytest.mark.asyncio
async def test_fix_rejected_if_not_owner(tmp_path):
    fixer, bridge, llm, dm, msg, bot, _, req_non_owner = make_fix(tmp_path)
    await fixer.fix(req_non_owner)
    llm.complete.assert_not_called()
    bridge.git_apply.assert_not_called()


@pytest.mark.asyncio
async def test_fix_rejected_if_file_missing(tmp_path):
    fixer, bridge, llm, dm, msg, bot, _, _ = make_fix(tmp_path)
    from wally_v2.core.self_fix import FixRequest
    req = FixRequest(requester_discord_id=OWNER_ID, file_path="nonexistent.py", description="x")
    await fixer.fix(req)
    llm.complete.assert_not_called()
    bridge.git_apply.assert_not_called()


@pytest.mark.asyncio
async def test_fix_sends_dm_with_diff_preview(tmp_path):
    diff = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n"
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path, llm_diff=diff)
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    llm.complete.assert_called_once()
    dm.send.assert_called()
    sent_text = dm.send.call_args_list[0][0][0]
    assert "bot/core/emotion.py" in sent_text
    assert "diff" in sent_text.lower() or "---" in sent_text or diff[:20] in sent_text


@pytest.mark.asyncio
async def test_fix_applies_on_checkmark(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    bridge.git_apply.assert_called_once()
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_fix_cancels_on_cross(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    bridge.git_apply.assert_not_called()
    bridge.docker_rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_fix_cancels_on_timeout(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

    await fixer.fix(req_owner)

    bridge.git_apply.assert_not_called()
    # DM cancellation message sent
    assert dm.send.call_count >= 2  # initial preview + timeout msg


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_dispatches_to_self_fix():
    from wally_v2.core.action_dispatcher import ActionDispatcher
    from wally_v2.core.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.fix = AsyncMock()

    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(
        action="ACT",
        act_name="code_fix",
        act_args={
            "requester_discord_id": OWNER_ID,
            "file_path": "bot/core/emotion.py",
            "description": "fix the bug",
        },
    )
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)  # let create_task run

    self_fix_mock.fix.assert_called_once()


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_rejects_non_owner():
    from wally_v2.core.action_dispatcher import ActionDispatcher
    from wally_v2.core.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.fix = AsyncMock()

    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(
        action="ACT",
        act_name="code_fix",
        act_args={
            "requester_discord_id": NON_OWNER_ID,
            "file_path": "bot/core/emotion.py",
            "description": "fix",
        },
    )
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)

    self_fix_mock.fix.assert_not_called()
```

- [ ] **Step 2: Run — expect ImportError**

```
python3 -m pytest tests/v2/core/test_self_fix.py -v
```
Expected: `ImportError: cannot import name 'SelfFix'`

- [ ] **Step 3: Write `wally_v2/core/self_fix.py`**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"

_FIX_SYSTEM = (
    "Tu es un assistant de correction de code Python. "
    "Génère UNIQUEMENT un diff unifié (format git diff) pour corriger le problème décrit. "
    "Le diff doit être applicable via `git apply`. "
    "Aucune explication — seulement le diff."
)


@dataclass
class FixRequest:
    requester_discord_id: str
    file_path: str       # relative to repo root, e.g. "bot/core/emotion.py"
    description: str


class SelfFix:
    def __init__(self, llm, bridge, bot, repo_root: str = "/app") -> None:
        self._llm = llm
        self._bridge = bridge
        self._bot = bot
        self._repo_root = Path(repo_root)

    async def fix(self, request: FixRequest) -> None:
        if request.requester_discord_id != OWNER_DISCORD_ID:
            logger.warning("SelfFix refusé: {} n'est pas owner", request.requester_discord_id)
            return

        abs_path = self._repo_root / request.file_path
        if not abs_path.exists():
            logger.warning("SelfFix: fichier {} introuvable", abs_path)
            return

        original = abs_path.read_text(encoding="utf-8")
        user_msg = (
            f"Fichier : {request.file_path}\n\n"
            f"```python\n{original[:6000]}\n```\n\n"
            f"Problème : {request.description}"
        )
        diff = await self._llm.complete(_FIX_SYSTEM, [{"role": "user", "content": user_msg}])

        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        preview = diff[:1800]
        msg = await dm.send(
            f"🔧 **Correction proposée — `{request.file_path}`**\n"
            f"```diff\n{preview}\n```\n"
            "✅ appliquer (rebuild + restart ~2min) · ❌ annuler · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=3600)
        except asyncio.TimeoutError:
            await dm.send("⏱ Timeout — correction annulée.")
            return

        if emoji == "✅":
            await dm.send("⚙️ Application du patch + rebuild...")
            try:
                await self._bridge.git_apply(diff)
                await self._bridge.docker_rebuild("wally")
            except Exception as e:
                await dm.send(f"❌ Erreur bridge: {e}")
        else:
            await dm.send("❌ Correction annulée.")

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
```

- [ ] **Step 4: Modify `wally_v2/core/action_dispatcher.py` — replace code_fix branch**

In `_act()`, find the `elif act_name == "code_fix":` block (currently just logs a warning) and replace it entirely:

```python
        elif act_name == "code_fix":
            self_fix = getattr(self._bot, "self_fix", None) if self._bot else None
            if self_fix is None:
                logger.warning(
                    "ACT code_fix: SelfFix non disponible (BRIDGE_SECRET non configuré)"
                )
                return
            requester_id = args.get("requester_discord_id", "")
            if requester_id != "610550333042589752":
                logger.warning("ACT code_fix refusé: {} n'est pas owner", requester_id)
                return
            from wally_v2.core.self_fix import FixRequest
            asyncio.create_task(
                self_fix.fix(
                    FixRequest(
                        requester_discord_id=requester_id,
                        file_path=args.get("file_path", ""),
                        description=args.get("description", ""),
                    )
                )
            )
```

Also add `import asyncio` at the top of `action_dispatcher.py` if not already present.

- [ ] **Step 5: Run — expect all passing**

```
python3 -m pytest tests/v2/core/test_self_fix.py tests/v2/core/test_action_dispatcher.py -v
```
Expected: `15 passed` (7 new + 5 existing dispatcher + 3 others)

- [ ] **Step 6: Commit**

```bash
git add wally_v2/core/self_fix.py wally_v2/core/action_dispatcher.py tests/v2/core/test_self_fix.py
git commit -m "feat(v2/c): add SelfFix + wire code_fix ACT with owner double-check"
```

---

### Task 16: Watchdog

**Files:**
- Create: `scripts/watchdog.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/test_watchdog.py`

**Interfaces:**
- Produces (standalone script, no imports from wally_v2):
  - `check_bot() -> bool`
  - `restart_bot() -> None`
  - `run() -> None` (infinite loop; tests stop it via patched `time.sleep`)

- [ ] **Step 1: Create `tests/scripts/__init__.py`**

```bash
touch tests/scripts/__init__.py
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/scripts/test_watchdog.py
import subprocess
import sys
import urllib.request
from unittest.mock import MagicMock, patch, call


class _MockResponse:
    def __init__(self, status: int):
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_check_bot_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda url, timeout: _MockResponse(200)
    )
    # import after patching so module-level globals use test values
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    assert wd.check_bot() is True


def test_check_bot_returns_false_on_error(monkeypatch):
    def raise_error(url, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", raise_error)
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    assert wd.check_bot() is False


def test_restart_bot_calls_docker_compose(monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
    monkeypatch.setattr(subprocess, "run", fake_run)
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)
    wd.restart_bot()
    assert len(calls) == 1
    assert "up" in calls[0]
    assert "wally" in calls[0]


def test_run_restarts_after_threshold(monkeypatch):
    """Simulates 3 failures then 1 success; asserts restart_bot called exactly once."""
    import importlib
    import scripts.watchdog as wd
    importlib.reload(wd)

    check_results = [False, False, False, True]
    check_iter = iter(check_results)
    sleep_calls = []
    restart_calls = []

    def fake_check():
        try:
            return next(check_iter)
        except StopIteration:
            raise SystemExit(0)

    def fake_sleep(n):
        sleep_calls.append(n)
        # After the 5th sleep (index 4), stop the loop
        if len(sleep_calls) >= 5:
            raise SystemExit(0)

    def fake_restart():
        restart_calls.append(1)

    monkeypatch.setattr(wd, "check_bot", fake_check)
    monkeypatch.setattr(wd, "restart_bot", fake_restart)
    monkeypatch.setattr("time.sleep", fake_sleep)

    try:
        wd.run()
    except SystemExit:
        pass

    assert len(restart_calls) == 1
```

- [ ] **Step 3: Run — expect ImportError or ModuleNotFoundError**

```
python3 -m pytest tests/scripts/test_watchdog.py -v
```
Expected: `ModuleNotFoundError: No module named 'scripts.watchdog'`

- [ ] **Step 4: Create `scripts/__init__.py` if missing and write `scripts/watchdog.py`**

```bash
touch scripts/__init__.py
```

```python
#!/usr/bin/env python3
"""Host-side watchdog: restarts wally-bot if health check fails 3 times in a row."""
import logging
import os
import subprocess
import time
import urllib.request

BOT_URL = os.environ.get("WATCHDOG_BOT_URL", "http://127.0.0.1:8080/api/admin/bot/status")
COMPOSE_FILE = os.environ.get("WATCHDOG_COMPOSE_FILE", "/opt/stacks/wally-ai/docker-compose.yml")
FAIL_THRESHOLD = int(os.environ.get("WATCHDOG_FAIL_THRESHOLD", "3"))
CHECK_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("watchdog")


def check_bot() -> bool:
    try:
        with urllib.request.urlopen(BOT_URL, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        log.warning("Health check failed: %s", e)
        return False


def restart_bot() -> None:
    log.warning("Restarting wally service via docker compose...")
    try:
        subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "wally"],
            timeout=60,
            check=True,
        )
        log.info("Restart command sent")
    except subprocess.CalledProcessError as e:
        log.error("Restart failed: %s", e)


def run() -> None:
    failures = 0
    log.info(
        "Watchdog started (url=%s, threshold=%d, interval=%ds)",
        BOT_URL, FAIL_THRESHOLD, CHECK_INTERVAL,
    )
    while True:
        if check_bot():
            if failures > 0:
                log.info("Bot recovered after %d failures", failures)
            failures = 0
        else:
            failures += 1
            log.warning("Bot unhealthy (%d/%d)", failures, FAIL_THRESHOLD)
            if failures >= FAIL_THRESHOLD:
                restart_bot()
                failures = 0
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
```

- [ ] **Step 5: Run — expect all passing**

```
python3 -m pytest tests/scripts/test_watchdog.py -v
```
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/watchdog.py tests/scripts/__init__.py tests/scripts/test_watchdog.py
git commit -m "feat(v2/c): add Watchdog (host-side health monitor, 3-strike restart)"
```

---

### Task 17: Wire bot.py

**Files:**
- Modify: `bot/discord/bot.py`
- Modify: `tests/test_memory_tag.py` (add `bot.self_fix = None`, `bot.self_upgrade = None`)
- Modify: `tests/test_discord_handlers.py` (same)

**Interfaces:**
- Consumes: `SelfFix(llm, bridge, bot, repo_root)`, `SelfUpgrade(update_checker, bridge, bot)`, `HostBridgeClient(socket_path, secret)`
- `bot.self_fix` and `bot.self_upgrade` initialized to `None` in `__init__`, conditionally set in `setup_hook`

- [ ] **Step 1: Add `self_fix = None` and `self_upgrade = None` to `WallyDiscord.__init__`**

In `bot/discord/bot.py`, find the block:
```python
        self.response_gate = None   # type: ignore[assignment]
        self.v2_memory = None       # type: ignore[assignment]  # MemoryRetrieval — câblé en Plan B
        self.cognitive_loop = None  # type: ignore[assignment]  # CognitiveLoop V2
```

Add two lines after `self.cognitive_loop = None`:
```python
        self.self_fix = None        # type: ignore[assignment]  # SelfFix V2 — câblé en Plan C
        self.self_upgrade = None    # type: ignore[assignment]  # SelfUpgrade V2 — câblé en Plan C
```

- [ ] **Step 2: Add SelfFix + SelfUpgrade init block in `setup_hook`**

After the cognitive_loop init block (which ends with `logger.info("CognitiveLoop V2 initialisée...")`), add:

```python
        import os as _os_auto
        _bridge_socket = _os_auto.getenv("BRIDGE_SOCKET_PATH", "/app/data/bridge.sock")
        _bridge_secret = _os_auto.getenv("BRIDGE_SECRET", "")
        if _bridge_socket and _bridge_secret:
            from wally_v2.core.host_bridge import HostBridgeClient
            from wally_v2.core.self_fix import SelfFix
            from wally_v2.core.self_upgrade import SelfUpgrade
            _bridge = HostBridgeClient(_bridge_socket, _bridge_secret)
            self.self_fix = SelfFix(self.llm_secondary, _bridge, self, repo_root="/app")
            _checker = getattr(self, "update_checker", None)
            if _checker is not None:
                self.self_upgrade = SelfUpgrade(_checker, _bridge, self)
            logger.info(
                "SelfFix initialisé (bridge={}){}", _bridge_socket,
                " + SelfUpgrade" if self.self_upgrade is not None else "",
            )
```

- [ ] **Step 3: Start/stop SelfUpgrade in `on_ready` / `close`**

In `on_ready`, after `self.cognitive_loop.start()`:
```python
        if self.self_upgrade is not None:
            self.self_upgrade.start()
```

In `close()`, before `await self.cognitive_loop.stop()`:
```python
        if self.self_upgrade is not None:
            await self.self_upgrade.stop()
```

- [ ] **Step 4: Add `bot.self_fix = None` and `bot.self_upgrade = None` to V1 test mocks**

In `tests/test_memory_tag.py`, find the line:
```python
    bot.cognitive_loop = None  # cognitive loop V2 désactivé dans les tests V1
```
Add immediately after:
```python
    bot.self_fix = None       # SelfFix V2 désactivé dans les tests V1
    bot.self_upgrade = None   # SelfUpgrade V2 désactivé dans les tests V1
```

In `tests/test_discord_handlers.py`, find the same `bot.cognitive_loop = None` line and add the same two lines after it.

- [ ] **Step 5: Run full V2 suite + affected V1 tests**

```
python3 -m pytest tests/v2/ tests/test_memory_tag.py tests/test_discord_handlers.py -q
```
Expected: `75+ passed` (67 V2 + script tests + V1 handler tests)

- [ ] **Step 6: Run full V1 suite to check for regressions**

```
python3 -m pytest tests/ -q --ignore=tests/v2 --ignore=tests/scripts
```
Expected: same pass count as before (1029 V1 tests, 2 pre-existing failures)

- [ ] **Step 7: Commit**

```bash
git add bot/discord/bot.py tests/test_memory_tag.py tests/test_discord_handlers.py
git commit -m "feat(v2/c): wire SelfFix + SelfUpgrade into bot setup_hook, on_ready, close"
```

---

## Self-Review

**Spec coverage:**
- ✅ Task 13: HostBridgeDaemon + HostBridgeClient — Unix socket, 4 routes, auth, service whitelist
- ✅ Task 14: SelfUpgrade — UpdateChecker integration, DM, ✅/❌ reaction, 24h timeout, docker-restart
- ✅ Task 15: SelfFix — code_fix ACT wired, owner double-check in dispatcher AND SelfFix.fix, DM preview, 1h timeout, git-apply + docker-rebuild
- ✅ Task 16: Watchdog — 3-strike threshold, 60s interval, docker compose up, env-configurable
- ✅ Task 17: bot.py wiring — `self_fix = None` + `self_upgrade = None` in `__init__`, gated on BRIDGE_SECRET, start/stop lifecycle, V1 mock compat
- ✅ `git apply --check` precedes `git apply` in daemon (Task 13 Step 4)
- ✅ `shell=True` + `start_new_session=True` for docker commands (Task 13 Step 4)
- ✅ OWNER_DISCORD_ID hardcoded in both `self_upgrade.py` and `self_fix.py`
- ✅ `ALLOWED_SERVICES = {"wally"}` in daemon

**Type consistency:**
- `HostBridgeClient.docker_restart(service: str)` ← `SelfUpgrade` calls `docker_restart("wally")` ✅
- `HostBridgeClient.git_apply(diff: str)` ← `SelfFix` calls `git_apply(diff)` ✅
- `HostBridgeClient.docker_rebuild(service: str)` ← `SelfFix` calls `docker_rebuild("wally")` ✅
- `SelfFix(llm, bridge, bot, repo_root: str)` ← `bot.py` passes `repo_root="/app"` ✅
- `SelfUpgrade(update_checker, bridge, bot)` ← `bot.py` passes `_checker` ✅
- `FixRequest(requester_discord_id, file_path, description)` ← `ActionDispatcher._act` constructs it ✅
