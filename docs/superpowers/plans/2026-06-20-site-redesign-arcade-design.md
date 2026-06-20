# Refonte site public — thème Arcade, câblé backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the public SPA (`public-ui/`) from glassmorphism to the arcade/retro theme of `docs/design/Wally.dc.html`, wire every section to the real backend, and add a live cognitive feed (Wally's "brain") plus 2 new endpoints.

**Architecture:** `public-ui/` stays a hash-router SPA (`index.html` shell + `app.js` router/SSE/canvas + `tabs/*.js` one module per section + `style.css`). The arcade mockup is a single scroll page; we keep the existing one-tab-mounted-at-a-time router and re-skin each tab. Canvas animated background + pixel flame sprites become global (rendered once in `index.html`, driven by `app.js`). Backend gains a `CognitiveFeed` fan-out broadcaster (same pattern as `sse.py`), a ranking endpoint, and `avg_response_ms` on the status endpoint. **No change to how the SPA is mounted** (`SPAStaticFiles` at `/`).

**Tech Stack:** Python 3 / asyncio / FastAPI / Starlette (backend), pytest + pytest-asyncio (tests), vanilla ES modules + Canvas 2D (frontend), Neo4j/Graphiti + aiosqlite (data), SSE via `text/event-stream`.

## Global Constraints

- **Logging:** `from loguru import logger` only — never `print()` / `import logging`.
- **Async I/O only** in the event loop; CPU-bound work via `asyncio.to_thread()`.
- **No backend mount change:** SPA served by `SPAStaticFiles` at `/`; new routes go under `/api/public` via `include_router(..., prefix="/api/public")` in `bot/dashboard/app.py`.
- **Route handlers** read shared services via `request.app.state.wally` (an `AppState`).
- **SSE fan-out pattern** (copy from `bot/dashboard/routes/sse.py`): module-level `list[asyncio.Queue]`, a `broadcast_*` function iterating a copy of the list with `put_nowait` (swallow `QueueFull`), an async generator that creates a queue, appends it, yields `data: {json}\n\n`, emits a keepalive comment on timeout, and removes the queue in a `finally`.
- **CognitiveFeed must be optional everywhere** (`feed=None` default, null-check before `publish`) so the V2 tests using `MagicMock` agents stay green.
- **Content truth (mockup lies — fix at wiring):** GPT-5 → **DeepSeek (deepseek-v4-pro / deepseek-v4-flash)**; Node.js → **Python/asyncio**; Sequelize / better-sqlite3 / SQLite → **aiosqlite + Qdrant**; Twitch IRC → **discord.py / twitchio**. Footer `github.com/KingsRequin/wallyAi` → `github.com/KingsRequin/wally-ai`. All fictitious stats → real API data.
- **Cognitive feed is PUBLIC and NON-anonymized** (user decision 2026-06-20): full names, full monologue, full decision detail. No truncation/masking required. (Still HTML-escape feed text on render — non-anonymized ≠ unescaped injection.)
- **Arcade palette (verbatim):** bg `#120a26` / radial `#2a1556`; text `#ffe8c2`; accents jaune `#ffd400`, rose `#ff3b6b`, violet `#7c4dff`, cyan `#43e0ff`, vert `#7CFC52`; muted `#6f6597` / `#9b8ad4`. Fonts: VT323 (body) + Press Start 2P (headings).
- **No JS test runner exists** in this repo (tests are pytest/Python). Frontend tasks (R3–R5) verify via: bot startup clean, `curl` of the wired endpoint, and a documented manual browser check. Backend tasks (R1, R2) are full TDD with pytest.
- **Each phase ≤5 files; stop and get approval between phases** (project rule).

---

## File Structure

**New files:**
- `bot/v2/core/cognitive_feed.py` — `CognitiveFeed` fan-out broadcaster + circular buffer.
- `bot/dashboard/routes/cognitive.py` — `GET /api/public/sse/cognitive` + `GET /api/public/cognitive/state`.
- `bot/dashboard/routes/community.py` — `GET /api/public/community/ranking`.
- `tests/v2/core/test_cognitive_feed.py`, `tests/dashboard/routes/test_cognitive_route.py`, `tests/dashboard/routes/test_community_ranking.py`, `tests/dashboard/routes/test_status_latency.py`, `tests/dashboard/test_appstate_latency.py`.

**Modified files:**
- `bot/v2/core/cognitive_loop.py` — accept `feed`, publish ATTN/THINK/DECIDE.
- `bot/v2/core/action_dispatcher.py` — accept `feed`, publish SPEAK/ACT/EVOLVE.
- `bot/discord/bot.py:104-139` — instantiate `CognitiveFeed`, inject into loop + dispatcher, store on `self`.
- `bot/dashboard/state.py` — add latency ring buffer + `record_response_time()` + `avg_response_ms`; add `cognitive_feed` field.
- `bot/dashboard/routes/status.py` — add `avg_response_ms` to payload.
- `bot/dashboard/routes/chat.py` — instrument web response timing.
- `bot/dashboard/app.py` — `include_router` for cognitive + community; expose feed on `app.state`.
- `public-ui/index.html` — arcade shell, fonts, bg canvas, scanlines, nav.
- `public-ui/style.css` — arcade theme (full rewrite of variables + classes).
- `public-ui/app.js` — port canvas fx + flame sprite, keep router/SSE, add cognitive SSE helper.
- `public-ui/tabs/{status,chat,gallery,journal,community,about}.js` — re-skin + wire.

---

# PHASE R1 — Backend: Cognitive Feed (socle du bloc phare)

## Task 1: CognitiveFeed broadcaster

**Files:**
- Create: `bot/v2/core/cognitive_feed.py`
- Test: `tests/v2/core/test_cognitive_feed.py`

**Interfaces:**
- Produces: `class CognitiveFeed` with `publish(event: dict) -> None`, `snapshot() -> list[dict]`, `subscribe() -> asyncio.Queue`, `unsubscribe(q: asyncio.Queue) -> None`. `publish` appends to a circular buffer (maxlen 30) and fans out to all subscriber queues (swallowing `QueueFull`).

- [ ] **Step 1: Write the failing test**

```python
# tests/v2/core/test_cognitive_feed.py
import asyncio
import pytest
from bot.v2.core.cognitive_feed import CognitiveFeed


def test_publish_appends_to_snapshot_buffer():
    feed = CognitiveFeed(buffer_size=3)
    feed.publish({"type": "THINK", "text": "a"})
    feed.publish({"type": "SPEAK", "detail": "b"})
    snap = feed.snapshot()
    assert [e["type"] for e in snap] == ["THINK", "SPEAK"]
    assert snap[0]["text"] == "a"


def test_buffer_is_circular():
    feed = CognitiveFeed(buffer_size=2)
    for i in range(5):
        feed.publish({"type": "THINK", "n": i})
    snap = feed.snapshot()
    assert [e["n"] for e in snap] == [3, 4]


@pytest.mark.asyncio
async def test_subscribe_receives_published_events():
    feed = CognitiveFeed()
    q = feed.subscribe()
    feed.publish({"type": "ACT", "detail": "x"})
    evt = await asyncio.wait_for(q.get(), timeout=1)
    assert evt["type"] == "ACT"
    feed.unsubscribe(q)
    assert q not in feed._queues


def test_publish_swallows_full_queue():
    feed = CognitiveFeed()
    q = feed.subscribe()
    for i in range(feed._queue_maxsize + 5):
        feed.publish({"type": "THINK", "n": i})
    assert True  # no exception
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/v2/core/test_cognitive_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.v2.core.cognitive_feed'`.

- [ ] **Step 3: Write minimal implementation**

```python
# bot/v2/core/cognitive_feed.py
from __future__ import annotations

import asyncio
from collections import deque


class CognitiveFeed:
    """Fan-out broadcaster for the cognitive loop's live events.

    Mirrors the SSE fan-out pattern in bot/dashboard/routes/sse.py: a list of
    per-subscriber asyncio.Queues plus a circular buffer of the last N events
    used to seed a client before the SSE stream takes over.
    """

    def __init__(self, buffer_size: int = 30, queue_maxsize: int = 50) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize

    def publish(self, event: dict) -> None:
        self._buffer.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def snapshot(self) -> list[dict]:
        return list(self._buffer)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/v2/core/test_cognitive_feed.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add bot/v2/core/cognitive_feed.py tests/v2/core/test_cognitive_feed.py
git commit -m "feat(v2): add CognitiveFeed fan-out broadcaster with circular buffer"
```

---

## Task 2: Emit events from the cognitive loop + dispatcher

**Files:**
- Modify: `bot/v2/core/cognitive_loop.py` (constructor + `_tick`, lines ~14-65)
- Modify: `bot/v2/core/action_dispatcher.py` (constructor + `_speak`/`_act`/`_evolve`)
- Test: `tests/v2/core/test_cognitive_loop.py` (add cases), `tests/v2/core/test_action_dispatcher.py` (add cases)

**Interfaces:**
- Consumes: `CognitiveFeed.publish` (Task 1).
- Produces: `CognitiveLoop.__init__(attention, monologue, meta, dispatcher, emotion_engine=None, feed=None)`; `ActionDispatcher.__init__(bot=None, persona_manager=None, fact_store=None, feed=None)`. Event shapes published:
  - `{"type": "ATTN", "target": <author|"—">, "content_snippet": <str>}`
  - `{"type": "THINK", "text": <monologue text>}`
  - `{"type": "DECIDE", "actions": [<action str>, ...]}`
  - `{"type": "SPEAK", "channel": <id>, "detail": <message>}`
  - `{"type": "ACT", "detail": <act_name + summary>}`
  - `{"type": "EVOLVE", "detail": <section>}`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/v2/core/test_cognitive_loop.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.v2.core.cognitive_loop import CognitiveLoop
from bot.v2.core.attention_agent import AttentionContext
from bot.v2.core.inner_monologue import MonologueResult
from bot.v2.core.meta_agent import MetaDecision


def _ctx():
    return AttentionContext(
        emotion_state={}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="matin",
    )


@pytest.mark.asyncio
async def test_tick_publishes_think_and_decide_to_feed():
    feed = MagicMock()
    attention, monologue, meta, dispatcher = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    attention.build_context = AsyncMock(return_value=_ctx())
    monologue.generate = AsyncMock(return_value=MonologueResult(text="je réfléchis", thought_fact_id=1))
    meta.decide = AsyncMock(return_value=[MetaDecision(action="THINK")])
    dispatcher.dispatch = AsyncMock()
    loop = CognitiveLoop(attention, monologue, meta, dispatcher, None, feed)

    await loop._tick()

    published = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "THINK" in published and "DECIDE" in published
    think = next(c.args[0] for c in feed.publish.call_args_list if c.args[0]["type"] == "THINK")
    assert think["text"] == "je réfléchis"


@pytest.mark.asyncio
async def test_tick_without_feed_does_not_crash():
    attention, monologue, meta, dispatcher = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    attention.build_context = AsyncMock(return_value=_ctx())
    monologue.generate = AsyncMock(return_value=MonologueResult(text="x", thought_fact_id=1))
    meta.decide = AsyncMock(return_value=[MetaDecision(action="THINK")])
    dispatcher.dispatch = AsyncMock()
    loop = CognitiveLoop(attention, monologue, meta, dispatcher)  # no feed
    await loop._tick()  # must not raise
```

```python
# append to tests/v2/core/test_action_dispatcher.py
import pytest
from unittest.mock import MagicMock
from bot.v2.core.action_dispatcher import ActionDispatcher
from bot.v2.core.meta_agent import MetaDecision


@pytest.mark.asyncio
async def test_speak_publishes_to_feed():
    feed = MagicMock()
    disp = ActionDispatcher(bot=MagicMock(), feed=feed)
    await disp.dispatch(MetaDecision(action="SPEAK", channel_id="123", message="salut"))
    types = [c.args[0]["type"] for c in feed.publish.call_args_list]
    assert "SPEAK" in types
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/v2/core/test_cognitive_loop.py tests/v2/core/test_action_dispatcher.py -v`
Expected: FAIL — `__init__` got unexpected keyword `feed`, or `THINK`/`SPEAK` not published.

- [ ] **Step 3: Modify `cognitive_loop.py`**

Read `bot/v2/core/cognitive_loop.py` first. Add `feed=None` to the constructor (store `self._feed = feed`), keeping every other existing line. In `_tick`, keep all current logic and add the three publish blocks:

```python
        context = await self._attention.build_context(emotion_state, self._recent_interactions)
        if self._feed:
            _last = self._recent_interactions[-1] if self._recent_interactions else {}
            self._feed.publish({
                "type": "ATTN",
                "target": _last.get("author", "—"),
                "content_snippet": (_last.get("content") or "")[:160],
            })
        result = await self._monologue.generate(context)
        if self._feed:
            self._feed.publish({"type": "THINK", "text": result.text})
        decisions = await self._meta.decide(result.text)
        if self._feed:
            self._feed.publish({"type": "DECIDE", "actions": [d.action for d in decisions]})
        for decision in decisions:
            await self._dispatcher.dispatch(decision)
```

> Use the exact variable names already in the file (`emotion_state`, `self._recent_interactions`). If `_recent_interactions` items use keys other than `author`/`content`, adapt the `.get(...)` keys to the real ones (read to confirm). The ATTN event must carry the interaction's author + a content snippet.

- [ ] **Step 4: Modify `action_dispatcher.py`**

Read `bot/v2/core/action_dispatcher.py` first. Add `feed=None` to the constructor (`self._feed = feed`). In `_speak`, at the existing `logger.info("Cognitive SPEAK ...")` line, add:

```python
        if self._feed:
            self._feed.publish({"type": "SPEAK", "channel": channel_id, "detail": message})
```

In `_act`, next to each existing `logger.info("ACT ...")` line, add (reusing the short text already in scope as `summary`):

```python
        if self._feed:
            self._feed.publish({"type": "ACT", "detail": f"{act_name}: {summary}"})
```

In `_evolve`, after `evolve()` succeeds:

```python
        if self._feed:
            self._feed.publish({"type": "EVOLVE", "detail": section})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/v2/core/ -v`
Expected: PASS (existing V2 tests + new ones). The pre-existing `_make_loop()` helper builds `CognitiveLoop` without `feed` → still valid.

- [ ] **Step 6: Commit**

```bash
git add bot/v2/core/cognitive_loop.py bot/v2/core/action_dispatcher.py tests/v2/core/test_cognitive_loop.py tests/v2/core/test_action_dispatcher.py
git commit -m "feat(v2): publish ATTN/THINK/DECIDE/SPEAK/ACT/EVOLVE to CognitiveFeed"
```

---

## Task 3: Public cognitive routes (SSE + snapshot)

**Files:**
- Create: `bot/dashboard/routes/cognitive.py`
- Modify: `bot/dashboard/state.py` (add `cognitive_feed` field)
- Modify: `bot/dashboard/app.py` (include router)
- Test: `tests/dashboard/routes/test_cognitive_route.py`

**Interfaces:**
- Consumes: `request.app.state.wally.cognitive_feed` (`CognitiveFeed | None`); its `snapshot()/subscribe()/unsubscribe()`.
- Produces: router `public_router` with `GET /cognitive/state` → `{"events": [...]}` and `GET /sse/cognitive` → `text/event-stream`. Registered under prefix `/api/public`.

- [ ] **Step 1: Add `cognitive_feed` to AppState**

In `bot/dashboard/state.py`, under the `TYPE_CHECKING` block add `from bot.v2.core.cognitive_feed import CognitiveFeed`, and add a field after `update_checker`:

```python
    cognitive_feed: Optional["CognitiveFeed"] = None
```

- [ ] **Step 2: Write the failing test**

```python
# tests/dashboard/routes/test_cognitive_route.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.v2.core.cognitive_feed import CognitiveFeed
from bot.dashboard.routes import cognitive


def _app_with_feed(feed):
    app = FastAPI()
    app.include_router(cognitive.public_router, prefix="/api/public")
    app.state.wally = SimpleNamespace(cognitive_feed=feed)
    return app


def test_state_returns_buffer_snapshot():
    feed = CognitiveFeed()
    feed.publish({"type": "THINK", "text": "salut"})
    r = TestClient(_app_with_feed(feed)).get("/api/public/cognitive/state")
    assert r.status_code == 200
    assert r.json()["events"][0]["type"] == "THINK"


def test_state_degrades_when_feed_absent():
    r = TestClient(_app_with_feed(None)).get("/api/public/cognitive/state")
    assert r.status_code == 200
    assert r.json() == {"events": []}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/dashboard/routes/test_cognitive_route.py -v`
Expected: FAIL — `ImportError: cannot import name 'cognitive'`.

- [ ] **Step 4: Write the route**

```python
# bot/dashboard/routes/cognitive.py
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

public_router = APIRouter()


@public_router.get("/cognitive/state")
async def cognitive_state(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)
    if feed is None:
        return {"events": []}
    return {"events": feed.snapshot()}


@public_router.get("/sse/cognitive")
async def cognitive_sse(request: Request):
    feed = getattr(request.app.state.wally, "cognitive_feed", None)

    async def gen():
        if feed is None:
            yield ": no-feed\n\n"
            return
        q = feed.subscribe()
        try:
            for evt in feed.snapshot():
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            feed.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 5: Register the router**

In `bot/dashboard/app.py`, beside the other public `include_router` calls (near `journal.public_router`), import `cognitive` with the other route imports and add:

```python
    app.include_router(cognitive.public_router, prefix="/api/public")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/dashboard/routes/test_cognitive_route.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/routes/cognitive.py bot/dashboard/state.py bot/dashboard/app.py tests/dashboard/routes/test_cognitive_route.py
git commit -m "feat(dashboard): public cognitive SSE + state snapshot routes"
```

---

## Task 4: Wire CognitiveFeed into the bot

**Files:**
- Modify: `bot/discord/bot.py:104-139`
- Modify: the `AppState(...)` construction site (grep `AppState(` — expected `bot/main.py`)

**Interfaces:**
- Consumes: `CognitiveFeed` (Task 1), loop/dispatcher feed params (Task 2), `AppState.cognitive_feed` (Task 3).
- Produces: `self.cognitive_feed` on the Discord bot; `AppState.cognitive_feed` populated.

- [ ] **Step 1: Instantiate + inject in `bot/discord/bot.py`**

Read `bot/discord/bot.py:100-145` first. Set `self.cognitive_feed = None` at the top of `__init__`. Inside the `cognitive_loop ... enabled` block, before agents:

```python
    from bot.v2.core.cognitive_feed import CognitiveFeed
    self.cognitive_feed = CognitiveFeed()
```

then pass it through:

```python
    _dispatcher = ActionDispatcher(bot=self, persona_manager=_persona_mgr, fact_store=_fact_store, feed=self.cognitive_feed)
    self.cognitive_loop = CognitiveLoop(_attention, _mono, _meta, _dispatcher, self.emotion, self.cognitive_feed)
```

- [ ] **Step 2: Pass feed to AppState**

Run: `grep -rn "AppState(" bot/ --include=*.py`. At the construction site pass `cognitive_feed=getattr(discord_bot, "cognitive_feed", None)`. If `AppState` is built before the Discord bot exists, instead set `app_state.cognitive_feed = getattr(discord_bot, "cognitive_feed", None)` after both exist.

- [ ] **Step 3: Verify imports compile**

Run: `python -c "import bot.discord.bot, bot.dashboard.state, bot.dashboard.app"`
Expected: exit 0, no output.

- [ ] **Step 4: Run V2 + cognitive route suites**

Run: `python -m pytest tests/v2/ tests/dashboard/routes/test_cognitive_route.py -q`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add bot/discord/bot.py bot/main.py
git commit -m "feat: wire CognitiveFeed into cognitive loop and expose via AppState"
```

**PHASE R1 GATE:** stop. Report, wait for approval before R2.

---

# PHASE R2 — Backend: Ranking + response time

## Task 5: avg_response_ms (AppState + status + instrumentation)

**Files:**
- Modify: `bot/dashboard/state.py`
- Modify: `bot/dashboard/routes/status.py`
- Modify: `bot/dashboard/routes/chat.py`
- Test: `tests/dashboard/test_appstate_latency.py`, `tests/dashboard/routes/test_status_latency.py`

**Interfaces:**
- Produces: `AppState.record_response_time(ms: float) -> None`; `AppState.avg_response_ms -> float | None` (None → endpoint emits `null`, UI shows `—`). Status payload gains `avg_response_ms`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dashboard/test_appstate_latency.py
from bot.dashboard.state import AppState


def _bare_state():
    s = AppState.__new__(AppState)  # bypass required dataclass fields
    s._init_latency()
    return s


def test_avg_none_when_empty():
    assert _bare_state().avg_response_ms is None


def test_avg_is_mean_of_samples():
    s = _bare_state()
    s.record_response_time(100.0)
    s.record_response_time(300.0)
    assert s.avg_response_ms == 200.0


def test_ring_buffer_bounded():
    s = _bare_state()
    for i in range(100):
        s.record_response_time(float(i))
    assert s.avg_response_ms == round(sum(range(50, 100)) / 50, 1)
```

```python
# tests/dashboard/routes/test_status_latency.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.dashboard.routes import status


def _client(avg):
    app = FastAPI()
    app.include_router(status.router, prefix="/api/public")
    app.state.wally = SimpleNamespace(
        start_time=0.0, message_count=0, message_count_discord=0,
        message_count_twitch=0, message_count_web=0,
        discord_bot=None, twitch_bot=None, config=SimpleNamespace(),
        avg_response_ms=avg,
    )
    return TestClient(app)


def test_status_includes_avg_response_ms():
    r = _client(123.4).get("/api/public/status")
    assert r.status_code == 200
    assert r.json()["avg_response_ms"] == 123.4
```

> The status test stubs only what `status.py` reads. If the handler reads more attributes, extend `SimpleNamespace` accordingly (read the handler first).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/dashboard/test_appstate_latency.py tests/dashboard/routes/test_status_latency.py -v`
Expected: FAIL — missing `_init_latency`/`record_response_time`/`avg_response_ms`; `avg_response_ms` absent from payload.

- [ ] **Step 3: Add latency support to AppState**

In `bot/dashboard/state.py`, add `from collections import deque` at top. Add to the dataclass:

```python
    _response_times: deque = field(default_factory=lambda: deque(maxlen=50))

    def _init_latency(self) -> None:
        from collections import deque as _dq
        self._response_times = _dq(maxlen=50)

    def record_response_time(self, ms: float) -> None:
        self._response_times.append(ms)

    @property
    def avg_response_ms(self):
        if not self._response_times:
            return None
        return round(sum(self._response_times) / len(self._response_times), 1)
```

- [ ] **Step 4: Add field to status payload**

In `bot/dashboard/routes/status.py`, add to the returned dict:

```python
        "avg_response_ms": getattr(state, "avg_response_ms", None),
```

- [ ] **Step 5: Instrument the web chat response**

Read `bot/dashboard/routes/chat.py` around where Wally's reply is generated (after the user message is persisted, where the reply text is produced / inserted with `is_wally=True`). Wrap with a monotonic timer (`time` is already imported, used at line 152):

```python
            _t0 = time.monotonic()
            # ... existing reply-generation call(s) unchanged ...
            state.record_response_time((time.monotonic() - _t0) * 1000.0)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/dashboard/test_appstate_latency.py tests/dashboard/routes/test_status_latency.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add bot/dashboard/state.py bot/dashboard/routes/status.py bot/dashboard/routes/chat.py tests/dashboard/test_appstate_latency.py tests/dashboard/routes/test_status_latency.py
git commit -m "feat(dashboard): avg_response_ms sliding window on status endpoint"
```

---

## Task 6: Community ranking endpoint

**Files:**
- Create: `bot/dashboard/routes/community.py`
- Modify: `bot/dashboard/app.py`
- Test: `tests/dashboard/routes/test_community_ranking.py`

**Interfaces:**
- Consumes: `request.app.state.wally.db` with `list_memory_users()`, `get_trust_scores_batch(pairs)`, `get_love_scores_batch(pairs)`.
- Produces: `public_router` with `GET /community/ranking` → `{"ranking": [{"name": str, "trait": str, "score": int|"MAX"}]}`. Azrael pinned last as `{"name": "Azrael", "trait": "intouchable", "score": "MAX"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/dashboard/routes/test_community_ranking.py
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.dashboard.routes import community


class _FakeDB:
    async def list_memory_users(self):
        return [
            {"platform": "twitch", "user_id": "1", "username": "zed"},
            {"platform": "twitch", "user_id": "2", "username": "gaby"},
        ]

    async def get_trust_scores_batch(self, pairs):
        return {("twitch", "1"): 0.9, ("twitch", "2"): 0.5}

    async def get_love_scores_batch(self, pairs):
        return {("twitch", "1"): 0.8, ("twitch", "2"): 0.7}


def _client(db):
    app = FastAPI()
    app.include_router(community.public_router, prefix="/api/public")
    app.state.wally = SimpleNamespace(db=db)
    return app


def test_ranking_sorted_desc_with_azrael_pinned():
    ranking = TestClient(_client(_FakeDB())).get("/api/public/community/ranking").json()["ranking"]
    names = [x["name"] for x in ranking]
    assert names[0] == "zed"
    assert ranking[-1]["name"] == "Azrael"
    assert ranking[-1]["score"] == "MAX"


def test_ranking_degrades_on_db_error():
    class _Boom:
        async def list_memory_users(self):
            raise RuntimeError("db down")
    r = TestClient(_client(_Boom())).get("/api/public/community/ranking")
    assert r.status_code == 200
    assert r.json()["ranking"][-1]["name"] == "Azrael"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/dashboard/routes/test_community_ranking.py -v`
Expected: FAIL — `cannot import name 'community'`.

- [ ] **Step 3: Write the route**

> Confirm the real user-listing method first: `grep -n "def list_memory_users\|def get_memory_users\|memory_users" bot/db/*.py bot/db/mixins/*.py`. The route + test assume `list_memory_users()` → dicts with `platform`/`user_id`/`username`. If the real signature differs, adapt route + test together.

```python
# bot/dashboard/routes/community.py
from __future__ import annotations

from fastapi import APIRouter, Request
from loguru import logger

public_router = APIRouter()

_AZRAEL = {"name": "Azrael", "trait": "intouchable", "score": "MAX"}


def _trait(trust: float, love: float) -> str:
    if love >= 0.7:
        return "wholesome"
    if trust >= 0.7:
        return "fiable"
    if trust < 0.3:
        return "sous surveillance"
    return "taquin"


@public_router.get("/community/ranking")
async def community_ranking(request: Request, limit: int = 10):
    db = request.app.state.wally.db
    try:
        users = await db.list_memory_users()
        pairs = [(u["platform"], u["user_id"]) for u in users]
        trust = await db.get_trust_scores_batch(pairs)
        love = await db.get_love_scores_batch(pairs)
        rows = []
        for u in users:
            name = (u.get("username") or "").strip()
            if not name or name.lower() == "azrael":
                continue
            t = trust.get((u["platform"], u["user_id"]), 0.0)
            lv = love.get((u["platform"], u["user_id"]), 0.0)
            rows.append({"name": name, "trait": _trait(t, lv), "score": round((t + lv) * 500)})
        rows.sort(key=lambda r: r["score"], reverse=True)
        rows = rows[:limit]
    except Exception as e:  # never 500 the public page
        logger.warning("community/ranking failed: {}", e)
        rows = []
    return {"ranking": [*rows, _AZRAEL]}
```

- [ ] **Step 4: Register the router**

In `bot/dashboard/app.py`, import `community` and add:

```python
    app.include_router(community.public_router, prefix="/api/public")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/dashboard/routes/test_community_ranking.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/community.py bot/dashboard/app.py tests/dashboard/routes/test_community_ranking.py
git commit -m "feat(dashboard): public community ranking endpoint (Azrael pinned)"
```

**PHASE R2 GATE:** stop. Run `python -m pytest tests/dashboard/ tests/v2/ -q`, report, wait for approval before R3.

---

# PHASE R3 — Frontend: Arcade shell + assets

> No JS test runner. Each task verifies via bot startup + browser check. Keep `app.js` router/SSE contracts intact: tabs still export `mount(el)`/`unmount()`; `emotions`, `onEmotionUpdate`, `connectSSE` stay.

## Task 7: Arcade shell — index.html

**Files:**
- Modify: `public-ui/index.html`

**Interfaces:**
- Produces: arcade DOM shell — `#bg-canvas`, scanline + vignette overlays, sticky nav (flame `#spx-nav` + WALLY wordmark + 6 `data-tab` buttons + EN LIGNE pill), `#tab-content` mount point, modal overlay (`#modal-overlay`/`#modal-img`/`#modal-caption`/`#modal-close`). Keeps `<script type="module" src="/app.js">`. Fonts VT323 + Press Start 2P.

- [ ] **Step 1: Replace head fonts + keep style/script links**

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=VT323&family=Press+Start+2P&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/style.css">
```

- [ ] **Step 2: Replace the body shell**

```html
<body>
  <canvas id="bg-canvas"></canvas>
  <div class="crt-scanlines"></div>
  <div class="crt-vignette"></div>

  <nav class="arc-nav">
    <div class="arc-brand" data-tab="status">
      <span class="flame" id="spx-nav"></span>
      <span class="arc-wordmark">WALLY</span>
    </div>
    <div class="arc-nav-tabs">
      <button class="arc-nav-btn" data-tab="status">STATUT</button>
      <button class="arc-nav-btn" data-tab="chat">CHAT</button>
      <button class="arc-nav-btn" data-tab="gallery">GALERIE</button>
      <button class="arc-nav-btn" data-tab="journal">JOURNAL</button>
      <button class="arc-nav-btn" data-tab="community">COMMUNAUTÉ</button>
      <button class="arc-nav-btn" data-tab="about">À PROPOS</button>
    </div>
    <div class="arc-online"><span class="dot"></span>EN LIGNE</div>
  </nav>

  <main id="tab-content" class="arc-main"></main>

  <div class="modal-overlay" id="modal-overlay">
    <div class="modal-box">
      <button class="modal-close" id="modal-close">✕</button>
      <img id="modal-img" alt="">
      <div class="modal-caption" id="modal-caption"></div>
    </div>
  </div>

  <footer class="arc-footer">
    fait avec une petite flamme · © 2026 Wally ·
    <span class="arc-link">github.com/KingsRequin/wally-ai</span>
  </footer>

  <script type="module" src="/app.js"></script>
</body>
```

> Decision: drop the separate mobile bottom-nav/sheet DOM; `.arc-nav` is responsive (wraps on narrow screens, Task 8). app.js bottom-sheet wiring is removed in Task 9.

- [ ] **Step 3: Verify served HTML**

Run: `python -c "h=open('public-ui/index.html').read(); assert all(s in h for s in ['bg-canvas','VT323','tab-content','wally-ai']); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add public-ui/index.html
git commit -m "feat(site): arcade shell — fonts, bg canvas, scanlines, nav"
```

---

## Task 8: Arcade theme — style.css

**Files:**
- Modify: `public-ui/style.css`

**Interfaces:**
- Produces: arcade CSS variables + classes used by shell + tabs: `.arc-nav`, `.arc-nav-btn(.active)`, `.arc-brand`, `.arc-wordmark`, `.arc-online`, `.arc-main`, `.arc-footer`, `.arc-link`, `.crt-scanlines`, `.crt-vignette`, `.flame`, `.arc-card`, `.arc-h2`, `.arc-eyebrow`, `.arc-sub`, `.arc-grid`, `.arc-stat-label/.arc-stat-value`, `.arc-pill`, `.emo-row/.emo-label/.emo-track/.emo-cell(.on)`, `.feed-row/.feed-time/.feed-tag/.feed-text`, `.modal-*`. Emotion color vars kept.

- [ ] **Step 1: Replace `:root` + base**

```css
:root {
  --bg: #120a26; --bg-radial: #2a1556; --text: #ffe8c2;
  --muted: #6f6597; --muted2: #9b8ad4;
  --yellow: #ffd400; --pink: #ff3b6b; --violet: #7c4dff; --cyan: #43e0ff; --green: #7CFC52;
  --card-bg: rgba(124,77,255,.08); --card-border: rgba(124,77,255,.30);
  --font-body: 'VT323', monospace; --font-head: 'Press Start 2P', monospace;
  --c-anger: #ef4444; --c-joy: #eab308; --c-curiosity: #22c55e; --c-sadness: #3b82f6; --c-boredom: #a855f7;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; overflow-x: hidden; }
body { margin: 0; color: var(--text); font-family: var(--font-body); min-height: 100vh;
  background: radial-gradient(130% 90% at 50% -10%, var(--bg-radial), var(--bg) 65%); }
```

- [ ] **Step 2: Background, nav, shell, footer**

```css
#bg-canvas { position: fixed; inset: 0; z-index: 0; pointer-events: none; width: 100%; height: 100%; }
.crt-scanlines { position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background: repeating-linear-gradient(rgba(0,0,0,0) 0,rgba(0,0,0,0) 2px,rgba(0,0,0,.2) 3px,rgba(0,0,0,0) 4px); }
.crt-vignette { position: fixed; inset: 0; z-index: 0; pointer-events: none; box-shadow: inset 0 0 200px rgba(0,0,0,.55); }
.arc-nav { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: clamp(6px,1.4vw,18px);
  flex-wrap: wrap; padding: 12px clamp(12px,3vw,32px); background: rgba(18,10,38,.82);
  backdrop-filter: blur(8px); border-bottom: 2px solid rgba(124,77,255,.32); }
.arc-brand { display: flex; align-items: center; gap: 12px; cursor: pointer; }
.arc-brand .flame { position: relative; width: 44px; height: 56px; display: inline-block; animation: bob 1.6s ease-in-out infinite; }
.arc-wordmark { font-family: var(--font-head); font-size: clamp(14px,2vw,20px); color: var(--yellow); text-shadow: 2px 2px 0 var(--pink); }
.arc-nav-tabs { display: flex; align-items: center; gap: clamp(8px,1.4vw,18px); flex-wrap: wrap;
  margin-left: clamp(6px,1.4vw,18px); font-size: clamp(15px,1.8vw,21px); }
.arc-nav-btn { background: none; border: none; cursor: pointer; font-family: var(--font-body); font-size: inherit;
  letter-spacing: 1px; padding: 4px 2px; white-space: nowrap; border-bottom: 2px solid transparent; color: #cdbff5; }
.arc-nav-btn.active { color: var(--yellow); border-bottom-color: var(--yellow); }
.arc-online { margin-left: auto; display: flex; align-items: center; gap: 8px; font-family: var(--font-head);
  font-size: 9px; color: var(--green); border: 2px solid rgba(124,255,82,.4); border-radius: 20px; padding: 7px 12px; }
.arc-online .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); }
.arc-main { position: relative; z-index: 1; max-width: 1180px; margin: 0 auto;
  padding: clamp(40px,7vw,80px) clamp(16px,4vw,40px); animation: fadeIn .4s ease; }
.arc-footer { position: relative; z-index: 1; text-align: center; padding: 40px 20px 50px; font-size: 19px;
  color: var(--muted); border-top: 2px solid rgba(124,77,255,.2); margin-top: 20px; }
.arc-link { color: var(--muted2); }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
```

- [ ] **Step 3: Reusable primitives**

```css
.arc-card { background: var(--card-bg); border: 2px solid var(--card-border); border-radius: 10px; padding: 20px; }
.arc-eyebrow { font-family: var(--font-head); font-size: 10px; letter-spacing: 1px; color: var(--muted2); }
.arc-h2 { font-family: var(--font-head); font-size: clamp(24px,5vw,46px); color: var(--yellow);
  text-shadow: 3px 3px 0 var(--pink), 6px 6px 0 var(--violet); letter-spacing: 1px; margin: 10px 0 4px; }
.arc-sub { font-size: clamp(18px,2.4vw,24px); opacity: .85; margin-bottom: 28px; }
.arc-grid { display: grid; gap: 16px; }
.arc-stat-label { font-family: var(--font-head); font-size: 9px; letter-spacing: 1px; }
.arc-stat-value { font-size: clamp(34px,5vw,50px); color: var(--text); line-height: 1; margin-top: 10px; }
.arc-pill { border: 2px solid rgba(124,255,82,.4); border-radius: 20px; padding: 5px 12px; font-size: 20px; display: inline-flex; gap: 6px; align-items: center; }
.emo-row { margin-bottom: 14px; }
.emo-label { font-family: var(--font-head); font-size: 9px; margin-bottom: 6px; }
.emo-track { display: flex; gap: 3px; }
.emo-cell { height: 14px; flex: 1; background: rgba(255,255,255,.12); }
.emo-cell.on { background: var(--cyan); }
.feed-row { display: flex; gap: 8px; padding: 3px 0; border-bottom: 1px solid rgba(124,77,255,.12); font-size: 20px; }
.feed-time { color: var(--muted); flex: none; }
.feed-tag { flex: none; font-family: var(--font-head); font-size: 8px; align-self: center; }
.feed-text { opacity: .92; }
.modal-overlay { position: fixed; inset: 0; z-index: 50; display: none; align-items: center; justify-content: center;
  background: rgba(8,4,18,.85); padding: 24px; }
.modal-overlay.open { display: flex; }
.modal-box { position: relative; max-width: 90vw; max-height: 90vh; }
.modal-box img { max-width: 100%; max-height: 80vh; border: 2px solid var(--card-border); border-radius: 8px; }
.modal-close { position: absolute; top: -14px; right: -14px; background: var(--yellow); color: #1a0a2e;
  border: none; border-radius: 50%; width: 34px; height: 34px; cursor: pointer; font-family: var(--font-head); font-size: 12px; }
.modal-caption { margin-top: 10px; font-size: 18px; color: var(--text); text-align: center; }
```

- [ ] **Step 4: Keyframes + responsive**

```css
@keyframes blink { 0%,49% { opacity: 1; } 50%,100% { opacity: 0; } }
@keyframes bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(10px); } }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--violet); border-radius: 6px; }
::-webkit-scrollbar-track { background: rgba(124,77,255,.12); }
input::placeholder { color: var(--muted); }
@media (max-width: 700px) { .arc-nav-tabs { font-size: 16px; gap: 10px; } .arc-online { display: none; } }
```

> Keep the old glassmorphism rules in place for now (un-migrated tabs still use `.glass` etc.); they are removed in Task 16 after all tabs are migrated.

- [ ] **Step 5: Verify CSS braces balance**

Run: `python -c "t=open('public-ui/style.css').read(); assert t.count('{')==t.count('}'), (t.count('{'),t.count('}')); print('braces ok')"`
Expected: `braces ok`.

- [ ] **Step 6: Commit**

```bash
git add public-ui/style.css
git commit -m "feat(site): arcade theme variables + reusable primitives"
```

---

## Task 9: app.js — canvas fx, flame sprite, router/SSE intact

**Files:**
- Modify: `public-ui/app.js`

**Interfaces:**
- Consumes: nav `data-tab` buttons, `#bg-canvas`, `#tab-content`, modal ids (Task 7).
- Produces (unchanged contracts): `export const emotions`, `export function onEmotionUpdate(fn)`, `connectSSE()` (`/api/public/sse/emotions`), hash router calling each tab's `mount(el)`/`unmount()`, `window.openModal(src, caption)` / `window.closeModal()`. New exports: `drawFlame(id, scale)`, `connectCognitiveSSE(onEvent) -> EventSource`, and the arcade background animation (default effect `aimant`, `localStorage("wally_mfx")`).

- [ ] **Step 1: Keep emotions + SSE; router on new shell**

Keep `emotions`, `onEmotionUpdate`, `notifyEmotions`, `connectSSE()` verbatim. Replace router + nav wiring (drop bottom-sheet logic):

```javascript
const TABS = { status, chat, gallery, journal, community, about };
let currentTab = null;

function syncNav(name) {
  document.querySelectorAll('.arc-nav-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
}
function route() {
  const name = location.hash.replace('#', '') || 'status';
  const tab = TABS[name] || TABS.status;
  if (currentTab && currentTab.unmount) currentTab.unmount();
  const host = document.getElementById('tab-content');
  host.innerHTML = '';
  syncNav(name);
  void host.offsetHeight;     // reflow → fade-in
  currentTab = tab;
  tab.mount(host);
  window.scrollTo({ top: 0 });
}
document.querySelectorAll('[data-tab]').forEach(el =>
  el.addEventListener('click', () => { location.hash = el.dataset.tab; }));
window.addEventListener('hashchange', route);
```

> `status`/`chat`/… are the imported tab namespaces. Keep the existing import lines. If imports are named (`mount as mountStatus`), shape `TABS` to `{ status: { mount: mountStatus, unmount: unmountStatus }, ... }` to match.

- [ ] **Step 2: Modal on new ids**

```javascript
window.openModal = (src, caption = '') => {
  document.getElementById('modal-img').src = src;
  document.getElementById('modal-caption').textContent = caption;
  document.getElementById('modal-overlay').classList.add('open');
};
window.closeModal = () => document.getElementById('modal-overlay').classList.remove('open');
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target.id === 'modal-overlay') window.closeModal();
});
document.getElementById('modal-close').addEventListener('click', window.closeModal);
```

- [ ] **Step 3: Flame sprite + cognitive SSE helper**

```javascript
export function drawFlame(id, P = 4) {
  const bm = [
    ".....O.....", "....OOO....", "....OYO....", "...OOYOO...", "...OYYYO...",
    "..OOYYYOO..", "..OYYWYYO..", ".OOYYWWYOO.", ".OYYWWWYYO.", ".OYYWWWYYO.",
    ".OOYYWYYOO.", "..OYYYYYO..", "..OOYYYOO..", "...OOOOO.."
  ];
  const pal = { O: "#ff4d1f", Y: "#ffb020", W: "#fff2c2" };
  const el = document.getElementById(id);
  if (!el) return;
  el.style.position = "relative"; el.style.display = "inline-block";
  el.style.width = (P * 11) + "px"; el.style.height = (P * 14) + "px";
  const dot = document.createElement('i');
  dot.style.position = "absolute"; dot.style.left = "0"; dot.style.top = "0";
  dot.style.width = P + "px"; dot.style.height = P + "px";
  const s = [];
  for (let r = 0; r < bm.length; r++)
    for (let c = 0; c < bm[r].length; c++) {
      const ch = bm[r][c];
      if (ch !== ".") s.push(`${c * P}px ${r * P}px 0 0 ${pal[ch]}`);
    }
  dot.style.boxShadow = s.join(",");
  el.innerHTML = ''; el.appendChild(dot);
}

export function connectCognitiveSSE(onEvent) {
  const es = new EventSource('/api/public/sse/cognitive');
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (_) {} };
  return es; // caller closes on unmount
}
```

- [ ] **Step 4: Port the animated background**

Port `setupCanvas`, `initParticles`, `newEmber`, `draw`, and `fxGrille/fxConstellation/fxAimant/fxVortex/fxOnde` from `docs/design/Wally.dc.html` (lines 423–585) into module-scope functions driven by one RAF loop. Replace `this.ctx/this.W/this.H/this.mpx/this.mpy/this.embers/this.nodes/this.orbs` with module-scope variables — keep the math identical. Effect read from `localStorage` (default `aimant`); mouse tracked via `mousemove`.

```javascript
// module scope: let ctx, W, H, mpx = null, mpy = null, embers, nodes, orbs, raf;
function currentMfx() {
  try {
    const v = localStorage.getItem('wally_mfx');
    return ['grille','constellation','aimant','vortex','onde'].includes(v) ? v : 'aimant';
  } catch (_) { return 'aimant'; }
}
// ...port fx* + setupCanvas/initParticles/newEmber/draw verbatim from the mockup...
// draw(ts): clearRect; embers with globalCompositeOperation='lighter'; then dispatch fx[currentMfx()](ts, mx, my).
```

- [ ] **Step 5: Bootstrap on load**

```javascript
setupCanvas();
connectSSE();   // emotions (existing)
route();        // initial render
drawFlame('spx-nav', 4);
```

- [ ] **Step 6: Verify — start bot + load page**

Run: `docker compose up -d --build` then `curl -s localhost:8080/ | grep -q bg-canvas && echo served`.
Manual: open site — background animates, nav switches tabs (hash changes), nav flame visible, console clean.

- [ ] **Step 7: Commit**

```bash
git add public-ui/app.js
git commit -m "feat(site): arcade bg canvas + flame sprite + cognitive SSE helper; router on new shell"
```

**PHASE R3 GATE:** stop. Report (shell renders, bg animates, router works), wait for approval before R4.

---

# PHASE R4 — Frontend: Sections câblées (re-skin + wire)

> Each tab keeps its `mount(el)`/`unmount()` signature and existing fetch/WS logic; only produced DOM + classes change to arcade, plus new data for STATUT/COMMUNAUTÉ. Verify each by loading its tab and confirming real data.

## Task 10: STATUT — status.js (stats + emotion bars + live cognitive feed)

**Files:**
- Modify: `public-ui/tabs/status.js`

**Interfaces:**
- Consumes: `GET /api/public/status` (now incl. `avg_response_ms`), `GET /api/public/twitch/stream`, `GET /api/public/emotions/history`, `onEmotionUpdate`+`emotions`, `connectCognitiveSSE` + `GET /api/public/cognitive/state` (seed).
- Produces: arcade STATUT — 4 stat cards (MESSAGES TRAITÉS=`total_messages`, VIEWERS EN MÉMOIRE=stream/memory count, TEMPS DE RÉPONSE=`avg_response_ms`→`—` if null, UPTIME from `uptime_seconds`), ACTIVITÉ EN DIRECT card (live cognitive feed), SERVICES card (real stack), PERSONNALITÉ emotion bars.

- [ ] **Step 1: Arcade layout + real stats**

Rewrite `mount(el)` to build arcade DOM with `.arc-card`/`.arc-stat-*`/`.arc-grid`. Format uptime from `uptime_seconds` (e.g. `14j 06h`); show `avg_response_ms` as `(ms/1000).toFixed(1)+'s'` or `—` when null. Services chips reflect real stack: DeepSeek, Discord/Twitch (from `discord_online`/`twitch_online`), Qdrant, Neo4j. Keep the 30s poll + emotion-history chart, restyled.

- [ ] **Step 2: Live cognitive feed (phare block)**

Seed from `GET /api/public/cognitive/state`, then subscribe via `connectCognitiveSSE`. Newest-first, cap ~12 rows. Escape text (untrusted).

```javascript
import { connectCognitiveSSE } from '../app.js';
const TAGC = { THINK:'#ffd400', SPEAK:'#43e0ff', ACT:'#7CFC52', DECIDE:'#bf94ff', ATTN:'#ff3b6b', EVOLVE:'#ff8a3b', SLEEP:'#6f6597' };
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function feedText(e){
  if (e.type==='THINK') return e.text;
  if (e.type==='SPEAK') return '→ '+(e.detail||'');
  if (e.type==='ATTN')  return (e.target||'—')+' : '+(e.content_snippet||'');
  if (e.type==='DECIDE')return (e.actions||[]).join(' · ');
  if (e.type==='ACT')   return e.detail||'';
  if (e.type==='EVOLVE')return 'persona → '+(e.detail||'');
  return e.detail||e.text||'';
}
function rowHtml(e){
  const t = new Date().toLocaleTimeString('fr-FR');
  return `<div class="feed-row"><span class="feed-time">${t}</span>`
       + `<span class="feed-tag" style="color:${TAGC[e.type]||'#fff'}">${escapeHtml(e.type)}</span>`
       + `<span class="feed-text">${escapeHtml(feedText(e))}</span></div>`;
}
```

Store the EventSource in a module var.

- [ ] **Step 3: unmount cleanup**

`unmount()` clears the poll interval, unsubscribes the emotion listener (existing), and calls `cognitiveES?.close()`.

- [ ] **Step 4: Verify**

Reload `#status`: real message count, uptime, `avg_response_ms` (or `—`), emotion bars move with SSE, cognitive rows appear as the loop ticks. Console clean.

- [ ] **Step 5: Commit**

```bash
git add public-ui/tabs/status.js
git commit -m "feat(site): arcade STATUT with real stats + live cognitive feed"
```

---

## Task 11: CHAT — chat.js (re-skin, zero regression)

**Files:**
- Modify: `public-ui/tabs/chat.js`

**Interfaces:**
- Consumes: existing `/ws/chat?token=`, `/api/chat/auth/*`, markdown renderer — unchanged.
- Produces: arcade chat panel (header WALLY + green dot + `twitch.tv/Azrael_TTV`, arcade bubbles, input + ENVOYER yellow pixel button). Login gate restyled arcade.

- [ ] **Step 1: Re-skin only.** Keep all auth (`getToken`/`tryRefresh`/`authedFetch`), WS handling, date navigation, imagine autocomplete, message types **unchanged**. Swap produced DOM classes to arcade (user name cyan, wally name yellow). Bot bubbles still `renderMarkdown`.
- [ ] **Step 2: Verify (regression-critical).** Login via Discord, send message: WS connects, reply streams, typing shows, `/imagine` works, memory column lists facts. Console clean. **No auth regression.**
- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/chat.js
git commit -m "feat(site): arcade re-skin of CHAT (auth/WS unchanged)"
```

---

## Task 12: GALERIE — gallery.js

**Files:**
- Modify: `public-ui/tabs/gallery.js`

**Interfaces:**
- Consumes: existing `/api/public/gallery*`, vote endpoints, `window.openModal`.
- Produces: arcade gallery grid (`.arc-card` tiles: real image + prompt + vote count), load-more, restyled modal.

- [ ] **Step 1:** Re-skin grid/tiles/modal; keep fetch/vote/pagination logic.
- [ ] **Step 2: Verify** — `#gallery` shows real images, vote works (authed), modal opens. Console clean.
- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/gallery.js
git commit -m "feat(site): arcade re-skin of GALERIE"
```

---

## Task 13: JOURNAL — journal.js (real daily entries, arcade cards)

**Files:**
- Modify: `public-ui/tabs/journal.js`

**Interfaces:**
- Consumes: existing `/api/public/journal`, `/api/public/journal/{date}/chart`.
- Produces: arcade journal — timeline/list of **real daily entries** (`date`, markdown `content`, emotion badges, chart img), each `.arc-card` with colored left border. **Not** the mockup's fake patch-notes.

- [ ] **Step 1:** Keep existing fetch + timeline + markdown + chart logic; re-skin to arcade cards. Map real fields (`date`, `content`, `word_count`, `has_chart`). Drop fictitious v2.0/GPT-5 changelog content.
- [ ] **Step 2: Verify** — `#journal` lists real entries; selecting one renders markdown + chart. Console clean.
- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/journal.js
git commit -m "feat(site): arcade JOURNAL bound to real daily entries"
```

---

## Task 14: COMMUNAUTÉ — community.js (ranking + social graph)

**Files:**
- Modify: `public-ui/tabs/community.js`

**Interfaces:**
- Consumes: NEW `GET /api/public/community/ranking`; existing `GET /api/public/social-graph/data` (already fetched at line 342).
- Produces: arcade community — channel card (`twitch.tv/Azrael_TTV`), "pour le réveiller" card, CLASSEMENT DES VIEWERS from `ranking` (rank #, name, trait, score; Azrael `∞ … MAX` pink), plus the existing force-directed graph restyled.

- [ ] **Step 1: Ranking fetch + render**

```javascript
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function loadRanking(host) {
  let ranking = [];
  try { ranking = (await (await fetch('/api/public/community/ranking')).json()).ranking || []; } catch (_) {}
  host.innerHTML = ranking.map((r, i) => {
    const isMax = r.score === 'MAX';
    const rk = isMax ? '∞' : '#' + (i + 1);
    const col = isMax ? 'var(--pink)' : (i === 0 ? 'var(--yellow)' : '#cdbff5');
    return `<div class="feed-row" style="font-size:22px;align-items:center">
      <span style="color:${col};width:40px;flex:none">${rk}</span>
      <span style="flex:1;color:${isMax?'var(--yellow)':'var(--text)'}">${escapeHtml(r.name)}</span>
      <span style="color:var(--muted);flex:none">${escapeHtml(r.trait)}</span>
      <span style="color:${isMax?'var(--pink)':'var(--cyan)'};width:70px;text-align:right;flex:none">${escapeHtml(r.score)}</span>
    </div>`;
  }).join('');
}
```

- [ ] **Step 2:** Keep existing social-graph fetch + force simulation; re-skin canvas card.
- [ ] **Step 3: Verify** — `#community` shows real ranking (Azrael MAX) + graph renders. Console clean.
- [ ] **Step 4: Commit**

```bash
git add public-ui/tabs/community.js
git commit -m "feat(site): arcade COMMUNAUTÉ with real ranking + social graph"
```

---

## Task 15: À PROPOS — about.js (content corrections)

**Files:**
- Modify: `public-ui/tabs/about.js`

**Interfaces:**
- Produces: arcade about — description, "comment il fonctionne" pipeline, "ce qu'il retient / ignore", gag officiel, SOUS LE CAPOT with corrected stack chips.

- [ ] **Step 1:** Re-skin to arcade + fix all false tech. Stack chips → **Python/asyncio, DeepSeek, aiosqlite, Qdrant, Neo4j, discord.py, twitchio**. Remove Node.js/GPT-5/Sequelize/better-sqlite3. Description "propulsé au GPT-5" → "propulsé par DeepSeek". Keep gag (`quoi → feur`).
- [ ] **Step 2: Verify** — `#about` arcade, no GPT-5/Node.js anywhere. Console clean.
- [ ] **Step 3: Commit**

```bash
git add public-ui/tabs/about.js
git commit -m "feat(site): arcade À PROPOS with corrected tech stack"
```

---

## Task 16: CSS cleanup (remove dead glassmorphism)

**Files:**
- Modify: `public-ui/style.css`

- [ ] **Step 1:** Confirm no remaining references: `grep -rn "glass\|blob-\|stars\|bottom-nav\|bnav-\|pipe-node\|pillar-" public-ui/tabs/ public-ui/index.html`. Remove only zero-reference rules.
- [ ] **Step 2: Verify** — `python -c "t=open('public-ui/style.css').read(); assert t.count('{')==t.count('}'); print('ok')"`; reload site, all tabs still styled.
- [ ] **Step 3: Commit**

```bash
git add public-ui/style.css
git commit -m "chore(site): remove dead glassmorphism CSS after arcade migration"
```

**PHASE R4 GATE:** stop. Report each section live with real data, wait for approval before R5.

---

# PHASE R5 — Integration

## Task 17: Full rebuild + verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite** — `python -m pytest -q`. Expected: all pass (existing ~989 + new). Fix any regression first.
- [ ] **Step 2: Rebuild + start** — `docker compose up -d --build && docker compose logs --tail=40 wally`. Expected: clean startup, no traceback, qdrant healthy, dashboard served.
- [ ] **Step 3: Endpoint smoke tests**

```bash
curl -s localhost:8080/api/public/status | python -m json.tool          # has avg_response_ms
curl -s localhost:8080/api/public/cognitive/state | python -m json.tool  # {"events":[...]}
curl -s localhost:8080/api/public/community/ranking | python -m json.tool # Azrael last, MAX
curl -s -N localhost:8080/api/public/sse/cognitive | head -c 200          # SSE emits
```

- [ ] **Step 4: Manual section walk-through** — each tab vs **Critères de succès**: arcade fidelity, STATUT real stats + live feed, CHAT (login/WS/memory, no regression), GALERIE/JOURNAL/COMMUNAUTÉ real data, responsive (DevTools mobile width), SSE reconnect (restart bot → feed resumes). Console clean everywhere.
- [ ] **Step 5: Final commit (if tweaks)**

```bash
git add -A
git commit -m "test(site): integration pass — arcade redesign wired end-to-end"
```

---

## Self-Review (author)

- **Spec coverage:** 6 sections → Tasks 10–15. Cognitive feed (feed/emit/SSE+state/wiring) → Tasks 1–4. Ranking → Task 6. avg_response_ms → Task 5. Shell/assets/canvas/flame → Tasks 7–9. Content corrections → Tasks 13/15 + Global Constraints. Error degradation → in each route (try/except → empty/`—`) + each tab (guarded fetch). Responsive → Task 8 + Task 17. No-regression chat → Task 11 + verify. New-backend tests → Tasks 1,2,3,5,6. CognitiveLoop behavior unchanged → optional-feed (Task 2) + existing tests green.
- **Type consistency:** event shapes (Task 2) consumed verbatim by `feedText` (Task 10). `avg_response_ms` (Task 5) consumed Task 10. `ranking` shape (Task 6) consumed Task 14. `drawFlame`/`connectCognitiveSSE` (Task 9) consumed Tasks 7/10.
- **Verification points flagged inline (read/grep before editing, adapt route+test together):** `_recent_interactions` keys (Task 2), `AppState(` site (Task 4), `list_memory_users` real name (Task 6), app.js import style (Task 9), `status.py` attributes for the stub (Task 5).
</content>
