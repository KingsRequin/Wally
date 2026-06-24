# Auto-modification autonome via Claude Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à Wally de décider seul de corriger une faiblesse de son code, après autorisation DM du créateur, en déléguant l'implémentation à Claude Code (au lieu d'un diff DeepSeek).

**Architecture:** Wally émet `[ACT code_fix {"goal": "..."}]` depuis sa boucle cognitive → `action_dispatcher` appelle `SelfFix.request_upgrade(goal)` → DM d'autorisation ✅/❌ → sur ✅, le host bridge lance `claude --dangerously-skip-permissions -p "<goal>"` en arrière-plan sur l'hôte, Wally poll le job, puis commit + rebuild + DM compte-rendu.

**Tech Stack:** Python 3.11, asyncio, discord.py, httpx (UDS), `http.server`/`socketserver` (daemon hôte), pytest + pytest-asyncio.

## Global Constraints

- **Nom d'action = `code_fix`** (PAS `self_upgrade` : la classe `SelfUpgrade` existe déjà pour le flux GHCR, sans rapport). Le spec parle de `self_upgrade` ; on l'implémente sous le nom `code_fix` pour éviter la collision.
- **OWNER_DISCORD_ID = `"610550333042589752"`** (verbatim, déjà défini dans `self_fix.py` et `self_upgrade.py`).
- **Claude lancé avec** `IS_SANDBOX=1 claude --dangerously-skip-permissions -p "<goal>" --output-format json`, `cwd=/opt/stacks/wally-ai` (repo hôte), en root.
- **Binaire claude** : `/root/.local/bin/claude` (configurable via env `CLAUDE_BIN`).
- **Repo conteneur** : `/app`. **Repo hôte** (où tourne le daemon + Claude) : `/opt/stacks/wally-ai`.
- **Logging** : `loguru` côté bot (`from loguru import logger`), `logging` stdlib côté daemon. Jamais de `print()`.
- **Aucun chemin d'échec silencieux** : tout échec dans `SelfFix` → DM au créateur via `_notify`.
- **Déploiement** : backend = rebuild image ; le daemon hôte se restart séparément (`scripts/host_bridge_daemon.py`).

---

## File Structure

| Fichier | Rôle | Action |
|---------|------|--------|
| `scripts/host_bridge_daemon.py` | daemon hôte root : endpoints git/docker + **Claude run/status/commit** | Modifier |
| `bot/intelligence/host_bridge.py` | client conteneur du bridge | Modifier |
| `bot/intelligence/self_fix.py` | orchestration auto-modif (DM autorisation → Claude → rebuild) | Réécrire |
| `bot/intelligence/action_dispatcher.py` | route `[ACT code_fix]` | Modifier (branche `code_fix`) |
| `bot/discord/bot.py` | câblage DI de `SelfFix` | Modifier (1 ligne) |
| `bot/intelligence/persona/prompts/reasoning_system.md` | documente l'action pour le LLM | Modifier |
| `bot/discord/handlers.py` | supprime l'ancien outil conversationnel | Modifier |
| `tests/intelligence/core/test_self_fix.py` | tests du nouveau flux | Réécrire |
| `tests/scripts/test_host_bridge_daemon.py` | test unitaire helper pur | Créer |

---

# PHASE 1 — Bridge (transport Claude)

## Task 1: Helpers + extraction résultat Claude dans le daemon hôte

**Files:**
- Modify: `scripts/host_bridge_daemon.py`
- Test: `tests/scripts/test_host_bridge_daemon.py` (create)

**Interfaces:**
- Produces: `_extract_claude_result(raw: str) -> str`, `_git_head() -> str`, `_git_status_porcelain() -> str` (module-level fns dans `scripts/host_bridge_daemon.py`). Constantes `JOBS_DIR: Path`, `CLAUDE_BIN: str`, `CLAUDE_TIMEOUT: float`, dict `_JOBS: dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_host_bridge_daemon.py`:

```python
import json
from scripts import host_bridge_daemon as d


def test_extract_claude_result_parses_json_result():
    raw = json.dumps({"type": "result", "result": "J'ai ajouté la lecture des réactions."})
    assert d._extract_claude_result(raw) == "J'ai ajouté la lecture des réactions."


def test_extract_claude_result_falls_back_to_tail_on_garbage():
    raw = "boom not json\n" * 5
    out = d._extract_claude_result(raw)
    assert "boom not json" in out


def test_extract_claude_result_empty():
    assert d._extract_claude_result("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/scripts/test_host_bridge_daemon.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_extract_claude_result'`

- [ ] **Step 3: Add imports, constants and helpers to `scripts/host_bridge_daemon.py`**

After the existing imports (top of file, after `from pathlib import Path`), add:

```python
import time
import uuid
```

After the existing constants block (after `ALLOWED_SERVICES`), add:

```python
JOBS_DIR = Path(os.environ.get("CLAUDE_JOBS_DIR", str(REPO_ROOT / "data" / "claude_jobs")))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/root/.local/bin/claude")
CLAUDE_TIMEOUT = float(os.environ.get("CLAUDE_TIMEOUT", "1800"))
_JOBS: dict[str, dict] = {}


def _git_head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _git_status_porcelain() -> str:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                       capture_output=True, timeout=10)
    return r.stdout.decode().strip()


def _extract_claude_result(raw: str) -> str:
    """claude -p --output-format json émet un objet JSON ; on en extrait le résultat."""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            val = obj.get("result") or obj.get("text") or ""
            return str(val)[:1500]
    except (json.JSONDecodeError, ValueError):
        pass
    return raw[-1500:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/scripts/test_host_bridge_daemon.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/host_bridge_daemon.py tests/scripts/test_host_bridge_daemon.py
git commit -m "feat(bridge): helpers git + extraction résultat Claude dans le daemon"
```

---

## Task 2: Endpoints `/claude-run`, `/claude-status`, `/claude-commit` (daemon hôte)

**Files:**
- Modify: `scripts/host_bridge_daemon.py` (méthode `do_POST` de `BridgeHandler`)

**Interfaces:**
- Consumes: `_JOBS`, `_git_head`, `_git_status_porcelain`, `_extract_claude_result`, `CLAUDE_BIN`, `CLAUDE_TIMEOUT`, `JOBS_DIR` (Task 1).
- Produces (contrat HTTP) :
  - `POST /claude-run {"goal"}` → `200 {"job_id"}` | `400` | `409`.
  - `POST /claude-status {"job_id"}` → `200 {"state":"running"}` ou `200 {"state":"done"|"failed","exit_code","result","changed","head_changed","output_tail"}` | `404`.
  - `POST /claude-commit {"goal"}` → `200 {"committed": bool, "hash"?}` | `500`.

- [ ] **Step 1: Add the three endpoint branches**

In `scripts/host_bridge_daemon.py`, inside `do_POST`, **after** the existing `elif self.path == "/docker-restart":` block and **before** the final `else:` clause, insert:

```python
        elif self.path == "/claude-run":
            goal = body.get("goal", "").strip()
            if not goal:
                self._send(400, {"error": "goal vide"})
                return
            if any(j.get("state") == "running" for j in _JOBS.values()):
                self._send(409, {"error": "un job Claude est déjà en cours"})
                return
            job_id = uuid.uuid4().hex
            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            out_path = JOBS_DIR / f"{job_id}.out"
            env = dict(os.environ)
            env["IS_SANDBOX"] = "1"
            outf = open(out_path, "wb")
            proc = subprocess.Popen(
                [CLAUDE_BIN, "--dangerously-skip-permissions", "-p", goal,
                 "--output-format", "json"],
                cwd=REPO_ROOT, env=env, stdout=outf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _JOBS[job_id] = {
                "state": "running", "proc": proc, "outf": outf,
                "out_path": str(out_path), "head_before": _git_head(),
                "goal": goal, "started_at": time.time(),
            }
            logging.info("claude-run job %s lancé (goal=%.60s)", job_id, goal)
            self._send(200, {"job_id": job_id})

        elif self.path == "/claude-status":
            job = _JOBS.get(body.get("job_id", ""))
            if job is None:
                self._send(404, {"error": "job inconnu"})
                return
            proc = job["proc"]
            rc = proc.poll()
            if rc is None:
                if time.time() - job["started_at"] > CLAUDE_TIMEOUT:
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except (ProcessLookupError, PermissionError):
                        pass
                    job["state"] = "failed"
                    self._send(200, {"state": "failed", "exit_code": -1,
                                     "result": "", "changed": False,
                                     "head_changed": False,
                                     "output_tail": "timeout dépassé"})
                    return
                self._send(200, {"state": "running"})
                return
            try:
                job["outf"].close()
            except OSError:
                pass
            raw = Path(job["out_path"]).read_text(errors="replace")
            head_after = _git_head()
            state = "done" if rc == 0 else "failed"
            job["state"] = state
            self._send(200, {
                "state": state, "exit_code": rc,
                "result": _extract_claude_result(raw),
                "changed": bool(_git_status_porcelain()),
                "head_changed": head_after != job["head_before"],
                "output_tail": raw[-2000:],
            })

        elif self.path == "/claude-commit":
            goal = body.get("goal", "")
            if not _git_status_porcelain():
                self._send(200, {"committed": False, "reason": "rien à committer"})
                return
            subprocess.run(["git", "add", "-A"], cwd=REPO_ROOT, check=True, timeout=30)
            r = subprocess.run(
                ["git", "commit", "-m", f"self-upgrade: {goal}"[:200]],
                cwd=REPO_ROOT, capture_output=True, timeout=30,
            )
            if r.returncode != 0:
                self._send(500, {"error": r.stderr.decode()})
                return
            self._send(200, {"committed": True, "hash": _git_head()})
```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('scripts/host_bridge_daemon.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Restart the daemon on the host and verify manually**

The daemon runs as root (PID visible via `ps aux | grep host_bridge_daemon`). Restart it:

```bash
# stop the current daemon, then relaunch (BRIDGE_SECRET must be set as it was)
pkill -f host_bridge_daemon.py
BRIDGE_SECRET="$(grep -m1 BRIDGE_SECRET /opt/stacks/wally-ai/.env | cut -d= -f2)" \
  setsid python3 /opt/stacks/wally-ai/scripts/host_bridge_daemon.py >/tmp/bridge.log 2>&1 &
sleep 1; cat /tmp/bridge.log
```

Verify the socket answers (health is GET, no auth):

```bash
curl --unix-socket /opt/stacks/wally-ai/data/bridge.sock http://bridge/health
```
Expected: `{"status": "ok"}`

> **Note:** A full `/claude-run` manual test is deferred to Phase 3 end-to-end verification (a real Claude run takes minutes and mutates the repo). Here we only confirm the daemon restarts cleanly and serves `/health`.

- [ ] **Step 4: Commit**

```bash
git add scripts/host_bridge_daemon.py
git commit -m "feat(bridge): endpoints claude-run/status/commit (spawn + poll, 1 job)"
```

---

## Task 3: Client conteneur `claude_run` / `claude_status` / `claude_commit`

**Files:**
- Modify: `bot/intelligence/host_bridge.py`

**Interfaces:**
- Produces: `HostBridgeClient.claude_run(goal: str) -> str`, `HostBridgeClient.claude_status(job_id: str) -> dict`, `HostBridgeClient.claude_commit(goal: str) -> dict` (toutes `async`). Lèvent `HostBridgeError` sur statut ≠ 200.

- [ ] **Step 1: Add the three methods**

In `bot/intelligence/host_bridge.py`, append these methods to the `HostBridgeClient` class (after `docker_restart`):

```python
    async def claude_run(self, goal: str) -> str:
        async with httpx.AsyncClient(transport=self._transport(), timeout=15.0) as c:
            r = await c.post(
                "http://bridge/claude-run",
                json={"goal": goal},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))
            return r.json()["job_id"]

    async def claude_status(self, job_id: str) -> dict:
        async with httpx.AsyncClient(transport=self._transport(), timeout=15.0) as c:
            r = await c.post(
                "http://bridge/claude-status",
                json={"job_id": job_id},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))
            return r.json()

    async def claude_commit(self, goal: str) -> dict:
        async with httpx.AsyncClient(transport=self._transport(), timeout=30.0) as c:
            r = await c.post(
                "http://bridge/claude-commit",
                json={"goal": goal},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))
            return r.json()
```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('bot/intelligence/host_bridge.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/intelligence/host_bridge.py
git commit -m "feat(bridge): client claude_run/claude_status/claude_commit"
```

---

# PHASE 2 — SelfFix + dispatch

## Task 4: Réécriture de `SelfFix` (autorisation → Claude → rebuild)

**Files:**
- Rewrite: `bot/intelligence/self_fix.py`
- Rewrite: `tests/intelligence/core/test_self_fix.py`

**Interfaces:**
- Consumes: `HostBridgeClient.claude_run/claude_status/claude_commit/docker_rebuild` (Task 3 + existant).
- Produces: `UpgradeRequest(goal: str)` (dataclass), `SelfFix(bridge, bot, *, poll_interval=10.0, approval_timeout=3600.0)`, `SelfFix.request_upgrade(req: UpgradeRequest) -> None` (async). Constante `OWNER_DISCORD_ID`.

- [ ] **Step 1: Write the failing tests**

Replace the entire content of `tests/intelligence/core/test_self_fix.py` with:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

OWNER_ID = "610550333042589752"


def make_fix(approval="✅", status_seq=None):
    """Build a SelfFix with mocked bridge + bot. Default: approval ✅, job done+changed."""
    from bot.intelligence.self_fix import SelfFix

    bridge = MagicMock()
    bridge.claude_run = AsyncMock(return_value="job123")
    if status_seq is None:
        status_seq = [{"state": "done", "exit_code": 0, "result": "fait",
                       "changed": True, "head_changed": False, "output_tail": ""}]
    bridge.claude_status = AsyncMock(side_effect=status_seq)
    bridge.claude_commit = AsyncMock(return_value={"committed": True, "hash": "abc"})
    bridge.docker_rebuild = AsyncMock()

    bot = MagicMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 7
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    reaction = MagicMock()
    reaction.emoji = approval
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    fixer = SelfFix(bridge, bot, poll_interval=0.0)
    return fixer, bridge, bot, dm


def req(goal="voir les réactions emoji"):
    from bot.intelligence.self_fix import UpgradeRequest
    return UpgradeRequest(goal=goal)


@pytest.mark.asyncio
async def test_approval_runs_claude_then_rebuilds():
    fixer, bridge, bot, dm = make_fix(approval="✅")
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_called_once()
    assert bridge.claude_run.call_args[0][0] == "voir les réactions emoji"
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_refusal_does_not_run_claude_and_records_decline():
    fixer, bridge, bot, dm = make_fix(approval="❌")
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()
    bridge.docker_rebuild.assert_not_called()
    # second identical request is ignored (declined)
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_cancels_without_running():
    fixer, bridge, bot, dm = make_fix()
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()
    assert dm.send.call_count >= 2  # proposal + cancellation


@pytest.mark.asyncio
async def test_claude_failure_notifies_no_rebuild():
    seq = [{"state": "failed", "exit_code": 1, "result": "", "changed": False,
            "head_changed": False, "output_tail": "boom"}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_not_called()
    assert any("échou" in c.args[0].lower() for c in dm.send.call_args_list)


@pytest.mark.asyncio
async def test_no_change_no_rebuild():
    seq = [{"state": "done", "exit_code": 0, "result": "rien", "changed": False,
            "head_changed": False, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_head_changed_triggers_rebuild():
    seq = [{"state": "done", "exit_code": 0, "result": "committed", "changed": False,
            "head_changed": True, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_empty_goal_is_ignored():
    fixer, bridge, bot, dm = make_fix()
    await fixer.request_upgrade(req(goal="   "))
    bot.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_polls_until_terminal():
    seq = [{"state": "running"}, {"state": "running"},
           {"state": "done", "exit_code": 0, "result": "ok", "changed": True,
            "head_changed": False, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    assert bridge.claude_status.call_count == 3
    bridge.docker_rebuild.assert_called_once()


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_dispatches_to_self_fix():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.request_upgrade = AsyncMock()
    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(action="ACT", act_name="code_fix",
                            act_args={"goal": "voir les réactions emoji"})
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)
    self_fix_mock.request_upgrade.assert_called_once()


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_ignores_empty_goal():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.request_upgrade = AsyncMock()
    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(action="ACT", act_name="code_fix", act_args={"goal": ""})
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)
    self_fix_mock.request_upgrade.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/intelligence/core/test_self_fix.py -v`
Expected: FAIL — `ImportError`/`AttributeError` (`UpgradeRequest`, `request_upgrade` n'existent pas).

- [ ] **Step 3: Rewrite `bot/intelligence/self_fix.py`**

Replace the entire content of `bot/intelligence/self_fix.py` with:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"


@dataclass
class UpgradeRequest:
    goal: str


class SelfFix:
    """Wally décide de se modifier ; le créateur autorise en DM ; Claude Code exécute."""

    def __init__(self, bridge, bot, *, poll_interval: float = 10.0,
                 approval_timeout: float = 3600.0) -> None:
        self._bridge = bridge
        self._bot = bot
        self._poll_interval = poll_interval
        self._approval_timeout = approval_timeout
        self._pending = False
        self._declined: set[str] = set()

    async def request_upgrade(self, req: UpgradeRequest) -> None:
        goal = (req.goal or "").strip()
        if not goal:
            return
        if self._pending:
            logger.info("self-upgrade ignoré: un upgrade est déjà en attente")
            return
        norm = goal.lower()
        if norm in self._declined:
            logger.info("self-upgrade ignoré: goal déjà refusé — {}", goal[:60])
            return
        self._pending = True
        try:
            await self._run_upgrade(goal, norm)
        except Exception as e:  # noqa: BLE001 — jamais d'échec silencieux
            logger.exception("self-upgrade a échoué")
            await self._notify(f"❌ Ma tentative d'auto-modification a échoué : {e}")
        finally:
            self._pending = False

    async def _run_upgrade(self, goal: str, norm: str) -> None:
        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        msg = await dm.send(
            "🧠 **J'ai repéré une faiblesse que je voudrais corriger :**\n"
            f"> {goal}\n\n"
            "Si tu autorises, **Claude Code** va modifier mon code dans ce sens "
            "(en autonomie), puis je redémarre avec la nouvelle version.\n"
            "✅ autoriser · ❌ refuser · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=self._approval_timeout)
        except asyncio.TimeoutError:
            await dm.send("⏱ Pas de réponse — j'abandonne cette idée.")
            self._declined.add(norm)
            return

        if emoji != "✅":
            await dm.send("❌ Ok, je laisse tomber. Je ne te le reproposerai pas.")
            self._declined.add(norm)
            return

        await dm.send("👍 C'est parti, Claude Code travaille… (ça peut prendre quelques minutes)")
        job_id = await self._bridge.claude_run(goal)

        status = await self._poll(job_id)
        if status is None:
            await dm.send("❌ Claude Code n'a pas répondu à temps — j'abandonne.")
            return
        if status.get("state") != "done":
            tail = (status.get("output_tail") or "")[-500:]
            await dm.send(
                f"❌ Claude Code a échoué (exit {status.get('exit_code')}).\n```\n{tail}\n```"
            )
            return
        if not status.get("changed") and not status.get("head_changed"):
            result = (status.get("result") or "").strip()[:500]
            await dm.send(f"🤔 Finalement aucun changement de code.\n{result}")
            return

        await dm.send("⚙️ Application + rebuild…")
        await self._bridge.claude_commit(goal)
        await self._bridge.docker_rebuild("wally")
        result = (status.get("result") or "").strip()[:800]
        await dm.send(f"✅ **C'est fait** — je redémarre (~2 min).\n{result}")

    async def _poll(self, job_id: str, max_wait: float = 1800.0) -> dict | None:
        waited = 0.0
        while waited <= max_wait:
            await asyncio.sleep(self._poll_interval)
            waited += self._poll_interval if self._poll_interval > 0 else 1.0
            status = await self._bridge.claude_status(job_id)
            if status.get("state") != "running":
                return status
        return None

    async def _notify(self, text: str) -> None:
        """DM best-effort au créateur. Ne propage jamais."""
        try:
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            await dm.send(text)
        except Exception:  # noqa: BLE001
            logger.exception("self-upgrade: impossible de notifier le créateur en DM")

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

- [ ] **Step 4: Run the SelfFix tests (dispatcher tests will still fail)**

Run: `python3 -m pytest tests/intelligence/core/test_self_fix.py -v -k "not dispatcher"`
Expected: PASS (8 passed) — the 2 `dispatcher` tests still fail until Task 5.

- [ ] **Step 5: Commit**

```bash
git add bot/intelligence/self_fix.py tests/intelligence/core/test_self_fix.py
git commit -m "feat(self-fix): autorisation DM → Claude Code → rebuild (remplace diff DeepSeek)"
```

---

## Task 5: Reshape de l'action `code_fix` dans le dispatcher

**Files:**
- Modify: `bot/intelligence/action_dispatcher.py:361-381`

**Interfaces:**
- Consumes: `SelfFix.request_upgrade`, `UpgradeRequest` (Task 4).
- Produces: branche `[ACT code_fix {"goal": "..."}]` → `self_fix.request_upgrade(UpgradeRequest(goal))`.

- [ ] **Step 1: Replace the `code_fix` branch**

In `bot/intelligence/action_dispatcher.py`, replace the entire `elif act_name == "code_fix":` block (lines 361-381) with:

```python
        elif act_name == "code_fix":
            self_fix = getattr(self._bot, "self_fix", None) if self._bot else None
            if self_fix is None:
                logger.warning(
                    "ACT code_fix: SelfFix non disponible (BRIDGE_SECRET non configuré)"
                )
                return
            goal = args.get("goal", "").strip()
            if not goal:
                logger.warning("ACT code_fix ignoré: goal vide")
                return
            from bot.intelligence.self_fix import UpgradeRequest
            asyncio.create_task(self_fix.request_upgrade(UpgradeRequest(goal=goal)))
            logger.info("ACT code_fix: demande d'auto-modif — {}", goal[:60])
            if self._feed:
                self._feed.publish({"type": "ACT", "detail": f"auto-modif : {goal[:60]}"})
```

- [ ] **Step 2: Run the dispatcher tests**

Run: `python3 -m pytest tests/intelligence/core/test_self_fix.py -v -k dispatcher`
Expected: PASS (2 passed).

- [ ] **Step 3: Run the full self_fix test file**

Run: `python3 -m pytest tests/intelligence/core/test_self_fix.py -v`
Expected: PASS (10 passed).

- [ ] **Step 4: Commit**

```bash
git add bot/intelligence/action_dispatcher.py
git commit -m "feat(dispatch): code_fix prend un goal et appelle request_upgrade"
```

---

## Task 6: Câblage DI de `SelfFix` (sans llm_secondary)

**Files:**
- Modify: `bot/discord/bot.py:162`

**Interfaces:**
- Consumes: `SelfFix(bridge, bot, ...)` (Task 4 — nouvelle signature, plus de `llm`/`repo_root`).

- [ ] **Step 1: Update the construction line**

In `bot/discord/bot.py`, replace line 162:

```python
            self.self_fix = SelfFix(self.llm_secondary, _bridge, self, repo_root="/app")
```

with:

```python
            self.self_fix = SelfFix(_bridge, self)
```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('bot/discord/bot.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add bot/discord/bot.py
git commit -m "chore(di): SelfFix construit sans llm_secondary"
```

---

# PHASE 3 — Prompt + nettoyage handlers

## Task 7: Documenter l'action `code_fix` dans le prompt de raisonnement

**Files:**
- Modify: `bot/intelligence/persona/prompts/reasoning_system.md` (section DÉCIDE, après la ligne `[ACT note_relation ...]`)

**Interfaces:**
- Consumes: rien (texte de prompt). Doit nommer l'action `code_fix` et le format `{"goal": "..."}` cohérent avec Task 5.

- [ ] **Step 1: Insert the action documentation**

In `bot/intelligence/persona/prompts/reasoning_system.md`, **after** the line beginning with `- `[ACT note_relation` (line 87) and **before** the line `- `[EVOLVE <section>` (line 89), insert:

```markdown
- `[ACT code_fix {"goal": "<la capacité ou la correction de code que tu veux>"}]` — quand tu identifies une **vraie limite technique de ton propre code** que seul un changement de code peut lever (ex. « je ne perçois pas les réactions emoji »). Décris le BUT recherché, pas le comment — **Claude Code** écrira le code à ta place. **Ton créateur doit autoriser** chaque demande en DM (✅/❌) ; s'il refuse, n'insiste pas et ne la repropose pas. Réservé aux vraies limites de code — PAS pour ton ton ou ta personnalité (utilise `[EVOLVE]`), PAS pour une envie vague. Geste rare et réfléchi.
```

- [ ] **Step 2: Verify the insertion**

Run: `grep -n "code_fix" bot/intelligence/persona/prompts/reasoning_system.md`
Expected: one line showing the new `[ACT code_fix ...]` entry within the DÉCIDE list.

- [ ] **Step 3: Commit**

```bash
git add bot/intelligence/persona/prompts/reasoning_system.md
git commit -m "feat(prompt): documenter l'action code_fix (auto-modif autorisée)"
```

---

## Task 8: Supprimer l'ancien outil conversationnel `request_self_modification`

**Files:**
- Modify: `bot/discord/handlers.py`

**Interfaces:**
- Produces: aucun. Retire l'outil owner-déclenché ; conserve l'amélioration `_fire` (log des exceptions).

- [ ] **Step 1: Remove the tool definition (lines ~84-115)**

In `bot/discord/handlers.py`, delete the entire `_SELF_MODIFY_TOOL` block including its leading comment — from the line `# Outil de self-modification — exposé UNIQUEMENT au créateur (voir _respond).` through the closing `}` of `_SELF_MODIFY_TOOL` (the line `}` after `}, ` `},`). Exact span to remove:

```python
# Outil de self-modification — exposé UNIQUEMENT au créateur (voir _respond).
# Déclenche SelfFix : génère un diff, l'envoie au créateur en DM, application
# seulement après approbation manuelle (✅). Wally ne doit l'utiliser que sur
# demande explicite de son créateur, jamais de sa propre initiative.
_SELF_MODIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "request_self_modification",
        "description": (
            "Demande une modification de ton propre code source. À utiliser UNIQUEMENT "
            "quand ton créateur te demande explicitement d'ajouter, corriger ou changer "
            "une de tes fonctionnalités. Tu fournis le fichier concerné et une description "
            "précise du changement. Ton créateur recevra le diff en privé et devra "
            "l'approuver manuellement avant toute application. Ne l'utilise JAMAIS de ta "
            "propre initiative ni pour quelqu'un d'autre que ton créateur."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Chemin du fichier à modifier, relatif à la racine du projet (ex: bot/discord/handlers.py)",
                },
                "description": {
                    "type": "string",
                    "description": "Description précise et autosuffisante du changement à apporter",
                },
            },
            "required": ["file_path", "description"],
        },
    },
}
```

- [ ] **Step 2: Remove the tool exposure gating (lines ~942-944)**

Delete this block (just after `tools.extend(_NOTE_TOOLS)`):

```python
        # Self-modification : réservée au créateur, et seulement si SelfFix est câblé.
        if str(message.author.id) == OWNER_DISCORD_ID and getattr(bot, "self_fix", None) is not None:
            tools.append(_SELF_MODIFY_TOOL)
```

- [ ] **Step 3: Remove the tool handler branch (lines ~1010-1030)**

Delete the entire `if name == "request_self_modification":` branch inside `_tool_executor_impl`:

```python
            if name == "request_self_modification":
                if str(message.author.id) != OWNER_DISCORD_ID or getattr(bot, "self_fix", None) is None:
                    return json.dumps({"status": "refused", "message": "Réservé au créateur, et mécanisme indisponible."})
                from bot.intelligence.self_fix import FixRequest
                file_path = args.get("file_path", "")
                # Valider le chemin AVANT de promettre un DM : sinon le LLM annonce
                # "c'est envoyé" alors que fix() abandonnera en silence.
                _abs, path_err = bot.self_fix.resolve(file_path)
                if path_err:
                    return json.dumps({"status": "error", "message": path_err})
                req = FixRequest(
                    requester_discord_id=str(message.author.id),
                    file_path=file_path,
                    description=args.get("description", ""),
                )
                # fix() attend l'approbation (jusqu'à 1h) → ne pas bloquer la réponse.
                _fire(bot.self_fix.fix(req))
                return json.dumps({
                    "status": "ok",
                    "message": "Demande validée. Le diff arrive dans tes DM — valide avec ✅ ou refuse avec ❌.",
                })
```

The line immediately after must remain: `            return f"Unknown tool: {name}"`.

- [ ] **Step 4: Remove the now-orphaned import (line 18)**

`OWNER_DISCORD_ID` is now only used by the deleted blocks. Verify, then delete the import:

Run: `grep -n "OWNER_DISCORD_ID" bot/discord/handlers.py`
Expected after deletions: only line 18 (`from bot.intelligence.self_fix import OWNER_DISCORD_ID`) remains → delete that line. Keep `from loguru import logger` and the improved `_fire` function untouched.

- [ ] **Step 5: Syntax check + full handler tests**

Run:
```bash
python3 -c "import ast; ast.parse(open('bot/discord/handlers.py').read()); print('OK')"
python3 -m pytest tests/ -q -k "handler or self_fix"
```
Expected: `OK` then all selected tests PASS, with no reference to `request_self_modification` remaining:

Run: `grep -rn "request_self_modification" bot/ tests/`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add bot/discord/handlers.py
git commit -m "refactor: retirer l'outil owner request_self_modification (un seul chemin: Wally décide)"
```

---

## Task 9: Vérification globale + déploiement end-to-end

**Files:** aucun (vérification).

- [ ] **Step 1: Full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: suite verte hormis les 2 échecs préexistants connus (spam + cost). Aucun nouvel échec.

- [ ] **Step 2: Restart the host daemon with the new endpoints (if not already done in Task 2)**

```bash
pkill -f host_bridge_daemon.py
BRIDGE_SECRET="$(grep -m1 BRIDGE_SECRET /opt/stacks/wally-ai/.env | cut -d= -f2)" \
  setsid python3 /opt/stacks/wally-ai/scripts/host_bridge_daemon.py >/tmp/bridge.log 2>&1 &
sleep 1
curl --unix-socket /opt/stacks/wally-ai/data/bridge.sock http://bridge/health
```
Expected: `{"status": "ok"}`

- [ ] **Step 3: Rebuild + redeploy the bot image**

```bash
cd /opt/stacks/wally-ai
export GIT_HASH=$(git rev-parse --short HEAD)
export BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker compose build wally && docker compose up -d wally
sleep 8
docker logs wally-bot --tail 20 2>&1 | grep -iE "ready|SelfFix|error"
```
Expected: `Discord bot ready`, `SelfFix initialisé`, no error.

- [ ] **Step 4: Real end-to-end test**

In Discord, prompt Wally (in conversation) toward recognizing a code limitation so it emits `[ACT code_fix {"goal": ...}]` autonomously (e.g. discuss the emoji-reactions limitation). Confirm:
  1. A DM arrives with the 🧠 authorization request showing the exact goal.
  2. React ❌ → Wally drops it and does not re-propose the same goal.
  3. Re-trigger, react ✅ → DM "👍 C'est parti", then after Claude finishes, a result DM + the bot rebuilds.

- [ ] **Step 5: Final commit (if any verification tweak was needed)**

```bash
git add -A
git commit -m "chore: vérification end-to-end auto-modif via Claude Code"
```

---

## Self-Review notes

- **Naming deviation logged:** spec dit `self_upgrade`, plan implémente `code_fix` (collision avec la classe `SelfUpgrade` GHCR). Documenté dans Global Constraints.
- **Decline persistence:** `_declined` est en mémoire process (reset au restart). Le spec évoque un « fait mémoire » ; v1 = en mémoire (suffit pour l'anti-emballement intra-session). Persistance cross-restart = amélioration future, hors scope.
- **Daemon tests:** seul le helper pur `_extract_claude_result` est testé unitairement (Task 1) ; les endpoints HTTP sont vérifiés manuellement (Task 2/9) car ils tournent en root sur l'hôte avec subprocess.
