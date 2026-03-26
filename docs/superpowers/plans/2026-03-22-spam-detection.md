# Spam Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect when a Discord user sends too many messages in a short time window, have Wally tell them to calm down (LLM-generated), mute them, remember the event, and increase anger when muted users keep talking.

**Architecture:** In-memory per-user/channel message tracker in `handlers.py`. When threshold is exceeded, `complete_secondary()` generates a warning message, `add_timeout()` mutes the user, and `memory.add()` stores the event. The `is_muted` block gains an anger delta. Config via nested `SpamDetectionConfig` dataclass. Dashboard admin extends existing config endpoints.

**Tech Stack:** Python asyncio, discord.py, aiosqlite, mem0, OpenAI API, FastAPI, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-22-spam-detection-design.md`

---

### Task 1: SpamDetectionConfig dataclass + Config.load/save

**Files:**
- Modify: `bot/config.py:46-54` (add dataclass before DiscordConfig, add field to DiscordConfig)
- Modify: `bot/config.py:151-154` (update Config.load for nested construction)
- Modify: `config.yaml` (add spam_detection section)
- Test: `tests/test_config_spam.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_spam.py
"""Tests for SpamDetectionConfig loading and saving."""
import os
import tempfile
import pytest
import yaml

from bot.config import Config, SpamDetectionConfig


def test_spam_detection_config_defaults():
    cfg = SpamDetectionConfig()
    assert cfg.enabled is True
    assert cfg.max_messages == 10
    assert cfg.window_seconds == 120
    assert cfg.mute_minutes == 5
    assert cfg.spam_anger_delta == 0.05
    assert cfg.exempt_channels == []


def test_config_load_with_spam_detection(tmp_path):
    """Config.load() correctly constructs nested SpamDetectionConfig."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({
        "bot": {
            "trigger_names": ["wally"],
            "language_default": "fr",
            "context_window_size": 20,
            "context_token_threshold": 3000,
            "journal_time": "08:00",
        },
        "openai": {
            "primary_model": "gpt-4o",
            "secondary_model": "gpt-4o-mini",
            "temperature": 0.9,
            "max_tokens": 500,
        },
        "discord": {
            "anger_trigger_threshold": 3,
            "timeout_minutes": 10,
            "spam_detection": {
                "enabled": True,
                "max_messages": 8,
                "window_seconds": 60,
                "mute_minutes": 3,
                "spam_anger_delta": 0.1,
                "exempt_channels": [123456],
            },
        },
        "twitch": {"guest_channels": [], "cooldown_seconds": 10},
        "emotions": {"anger": {"decay_lambda": 0.01}},
        "twitch_events": {},
    }))
    cfg = Config.load(str(config_path))
    assert isinstance(cfg.discord.spam_detection, SpamDetectionConfig)
    assert cfg.discord.spam_detection.max_messages == 8
    assert cfg.discord.spam_detection.exempt_channels == [123456]


def test_config_load_without_spam_detection_uses_defaults(tmp_path):
    """Config.load() provides defaults when spam_detection is missing from YAML."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({
        "bot": {
            "trigger_names": ["wally"],
            "language_default": "fr",
            "context_window_size": 20,
            "context_token_threshold": 3000,
            "journal_time": "08:00",
        },
        "openai": {
            "primary_model": "gpt-4o",
            "secondary_model": "gpt-4o-mini",
            "temperature": 0.9,
            "max_tokens": 500,
        },
        "discord": {"anger_trigger_threshold": 3, "timeout_minutes": 10},
        "twitch": {"guest_channels": [], "cooldown_seconds": 10},
        "emotions": {},
        "twitch_events": {},
    }))
    cfg = Config.load(str(config_path))
    assert cfg.discord.spam_detection.enabled is True
    assert cfg.discord.spam_detection.max_messages == 10


def test_config_save_roundtrip_spam_detection(tmp_path):
    """Config.save() persists spam_detection and Config.load() can read it back."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({
        "bot": {
            "trigger_names": ["wally"],
            "language_default": "fr",
            "context_window_size": 20,
            "context_token_threshold": 3000,
            "journal_time": "08:00",
        },
        "openai": {
            "primary_model": "gpt-4o",
            "secondary_model": "gpt-4o-mini",
            "temperature": 0.9,
            "max_tokens": 500,
        },
        "discord": {
            "anger_trigger_threshold": 3,
            "timeout_minutes": 10,
            "spam_detection": {"max_messages": 15, "mute_minutes": 7},
        },
        "twitch": {"guest_channels": [], "cooldown_seconds": 10},
        "emotions": {},
        "twitch_events": {},
    }))
    cfg = Config.load(str(config_path))
    cfg.discord.spam_detection.window_seconds = 90
    cfg.save()

    cfg2 = Config.load(str(config_path))
    assert cfg2.discord.spam_detection.max_messages == 15
    assert cfg2.discord.spam_detection.window_seconds == 90
    assert cfg2.discord.spam_detection.mute_minutes == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_spam.py -v`
Expected: ImportError — `SpamDetectionConfig` does not exist yet

- [ ] **Step 3: Add SpamDetectionConfig dataclass and update DiscordConfig**

In `bot/config.py`, add before `DiscordConfig` (line 46):
```python
@dataclass
class SpamDetectionConfig:
    enabled: bool = True
    max_messages: int = 10
    window_seconds: int = 120
    mute_minutes: int = 5
    spam_anger_delta: float = 0.05
    exempt_channels: list[int] = field(default_factory=list)
```

Add field to `DiscordConfig`:
```python
spam_detection: SpamDetectionConfig = field(default_factory=SpamDetectionConfig)
```

- [ ] **Step 4: Update Config.load() for nested construction**

Replace line 154 (`discord=DiscordConfig(**raw["discord"]),`) with:
```python
discord_raw = dict(raw.get("discord", {}))
spam_raw = discord_raw.pop("spam_detection", {})
```
And in the `cls(...)` call:
```python
discord=DiscordConfig(**discord_raw, spam_detection=SpamDetectionConfig(**spam_raw)),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_spam.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Add spam_detection to config.yaml**

Under the `discord:` section in `config.yaml`:
```yaml
  spam_detection:
    enabled: true
    max_messages: 10
    window_seconds: 120
    mute_minutes: 5
    spam_anger_delta: 0.05
    exempt_channels:
      - 1485380606224502844
```

- [ ] **Step 7: Run full test suite to check no regressions**

Run: `python -m pytest --tb=short -q`
Expected: all existing tests pass (the `make_bot()` mock may need `spam_detection` config added — see Task 3)

- [ ] **Step 8: Commit**

```bash
git add bot/config.py config.yaml tests/test_config_spam.py
git commit -m "feat: add SpamDetectionConfig dataclass with nested config loading"
```

---

### Task 2: Prompt template for spam warning

**Files:**
- Create: `bot/persona/prompts/spam_warning_system.md`

- [ ] **Step 1: Create the prompt file**

```markdown
Tu as détecté qu'un utilisateur envoie beaucoup trop de messages dans un court laps de temps.
Tu en as marre de ce comportement. Tu dois lui dire de se calmer et de ralentir.
Formule ta réponse en une ou deux phrases maximum. Sois direct et agacé.
Ne mentionne pas de chiffres exacts, ni de durée de mute.
```

- [ ] **Step 2: Commit**

```bash
git add bot/persona/prompts/spam_warning_system.md
git commit -m "feat: add spam warning system prompt template"
```

---

### Task 3: Spam tracker + _check_spam() in handlers.py

**Files:**
- Modify: `bot/discord/handlers.py:1-10` (imports, module-level dict)
- Modify: `bot/discord/handlers.py:136-222` (handle_message flow)
- Test: `tests/test_spam_detection.py`

- [ ] **Step 1: Write tests for spam detection**

```python
# tests/test_spam_detection.py
"""Tests for Discord spam detection and mute-anger behavior."""
import time
import pytest
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import handle_message, _check_spam, _spam_tracker


def _make_spam_bot(spam_enabled=True, max_messages=5, window_seconds=10,
                   mute_minutes=5, spam_anger_delta=0.05, exempt_channels=None,
                   muted=False):
    """Build a mock bot with spam detection config."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.bot.spontaneous_discord_enabled = False
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.channel_filter_mode = "none"
    bot.config.discord.channel_whitelist = []
    bot.config.discord.channel_blacklist = []
    bot.config.discord.spam_detection.enabled = spam_enabled
    bot.config.discord.spam_detection.max_messages = max_messages
    bot.config.discord.spam_detection.window_seconds = window_seconds
    bot.config.discord.spam_detection.mute_minutes = mute_minutes
    bot.config.discord.spam_detection.spam_anger_delta = spam_anger_delta
    bot.config.discord.spam_detection.exempt_channels = exempt_channels or []

    bot.db.is_muted = AsyncMock(return_value=muted)
    bot.db.is_welcomed = AsyncMock(return_value=True)
    bot.db.add_timeout = AsyncMock()
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.get_opinions = AsyncMock(return_value=[])
    bot.config.bot.love_decay_lambda = 0.02

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.2, "joy": 0.3, "sadness": 0.0, "curiosity": 0.2, "boredom": 0.0}
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.emotion.process_message = AsyncMock(return_value=None)
    bot.emotion.apply_delta = MagicMock()

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")
    bot.memory.add = AsyncMock()
    bot.memory.search_relationships = AsyncMock(return_value="")

    bot.language.detect = MagicMock(return_value="fr")
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.openai.complete = AsyncMock(return_value="Bonjour!")
    bot.openai.complete_secondary = AsyncMock(return_value="Calme-toi un peu.")

    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona block")
    bot.web_search = None
    bot.apex_api = None

    return bot


def _make_msg(content="salut", channel_id=777, guild_id=99999, user_id=12345):
    msg = MagicMock()
    msg.content = content
    msg.author.bot = False
    msg.author.id = user_id
    msg.author.display_name = "TestUser"
    msg.guild.id = guild_id
    msg.channel.id = channel_id
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = []
    msg.reference = None
    return msg


@pytest.fixture(autouse=True)
def clear_spam_tracker():
    """Reset spam tracker between tests."""
    _spam_tracker.clear()
    yield
    _spam_tracker.clear()


@pytest.mark.asyncio
async def test_spam_triggers_after_threshold():
    """User exceeding max_messages in window triggers mute + warning."""
    bot = _make_spam_bot(max_messages=3, window_seconds=60)
    msg = _make_msg(content="wally hey")
    msg.mentions = [bot.user]  # triggered

    # Send 3 messages — third should trigger spam
    with patch("bot.discord.handlers.asyncio.create_task"):
        for _ in range(2):
            await handle_message(bot, msg)
        # Reset mocks to check only the 3rd call
        msg.channel.send.reset_mock()
        bot.db.add_timeout.reset_mock()

        await handle_message(bot, msg)

    # Spam warning sent
    msg.channel.send.assert_awaited_once()
    # Mute activated
    bot.db.add_timeout.assert_awaited_once()
    # Memory fact stored
    bot.memory.add.assert_awaited()


@pytest.mark.asyncio
async def test_spam_disabled_does_not_trigger():
    """When spam detection is disabled, no mute even with many messages."""
    bot = _make_spam_bot(spam_enabled=False, max_messages=2)
    msg = _make_msg(content="wally hey")
    msg.mentions = [bot.user]

    with patch("bot.discord.handlers.asyncio.create_task"):
        for _ in range(5):
            await handle_message(bot, msg)

    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_exempt_channel_skips_spam_check():
    """Messages in exempt channels don't count toward spam."""
    bot = _make_spam_bot(max_messages=2, exempt_channels=[777])
    msg = _make_msg(content="wally hey", channel_id=777)
    msg.mentions = [bot.user]

    with patch("bot.discord.handlers.asyncio.create_task"):
        for _ in range(5):
            await handle_message(bot, msg)

    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_muted_user_anger_increases():
    """Messages from muted users increase Wally's anger."""
    bot = _make_spam_bot(muted=True, spam_anger_delta=0.05)
    msg = _make_msg(content="wally hey")
    msg.mentions = [bot.user]

    await handle_message(bot, msg)

    bot.emotion.apply_delta.assert_called_once_with("anger", 0.05)
    # Should react with emoji, not reply
    msg.add_reaction.assert_awaited_once()
    msg.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_spam_tracker_cleans_old_entries():
    """Old timestamps outside the window are purged."""
    bot = _make_spam_bot(max_messages=3, window_seconds=10)
    msg = _make_msg(content="wally hey")
    msg.mentions = [bot.user]

    # Manually inject old timestamps
    key = (str(msg.author.id), str(msg.channel.id))
    _spam_tracker[key] = deque([time.time() - 20, time.time() - 15])

    # This should NOT trigger spam (old entries purged, only 1 new)
    await handle_message(bot, msg)

    bot.db.add_timeout.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_spam_detection.py -v`
Expected: ImportError — `_check_spam` and `_spam_tracker` don't exist

- [ ] **Step 3: Add spam tracker and _check_spam() to handlers.py**

Add import at top of `bot/discord/handlers.py`:
```python
from collections import deque
```

Add module-level dict after `_spontaneous_cooldowns`:
```python
_spam_tracker: dict[tuple[str, str], deque] = {}
```

Add `_check_spam()` function (before `handle_message`):
```python
async def _check_spam(bot: "WallyDiscord", message: discord.Message) -> bool:
    """Track message rate and trigger spam mute if threshold exceeded.

    Returns True if spam was detected and handled (caller should return early).
    """
    cfg = bot.config.discord.spam_detection
    if not cfg.enabled:
        return False

    if not message.guild:
        return False

    channel_id = message.channel.id
    if channel_id in cfg.exempt_channels:
        return False

    user_id = str(message.author.id)
    key = (user_id, str(channel_id))
    now = time.time()
    cutoff = now - cfg.window_seconds

    dq = _spam_tracker.get(key)
    if dq is None:
        dq = deque()
        _spam_tracker[key] = dq

    # Purge old timestamps
    while dq and dq[0] < cutoff:
        dq.popleft()

    # Clean up empty entries before adding new one
    if not dq:
        _spam_tracker.pop(key, None)

    dq.append(now)

    if len(dq) < cfg.max_messages:
        return False

    # --- Spam detected ---
    guild_id = str(message.guild.id)
    username = message.author.display_name
    anger = bot.emotion.get_state().get("anger", 0.0)

    # Generate LLM warning
    from bot.core.prompts import load_prompt
    system = load_prompt("spam_warning_system", "Dis à l'utilisateur de se calmer.")
    user_msg = (
        f"L'utilisateur {username} a envoyé {len(dq)} messages "
        f"en {cfg.window_seconds} secondes."
    )
    try:
        warning = await bot.openai.complete_secondary(
            system_prompt=system,
            messages=[{"role": "user", "content": user_msg}],
            purpose="spam_warning",
            user_id=user_id,
        )
        await message.channel.send(warning)
    except Exception as e:
        logger.error("Spam warning LLM failed: {e}", e=e)
        await message.channel.send(f"{username}, calme-toi un peu. 😤")

    # Mute user
    await bot.db.add_timeout(user_id, guild_id, cfg.mute_minutes, anger)

    # Store memory fact
    try:
        await bot.memory.add(
            "discord", user_id,
            f"Wally a coupé {username} pour spam — trop de messages en peu de temps. "
            f"Il en a eu marre et a arrêté de lui répondre.",
            username=username,
        )
    except Exception as e:
        logger.warning("Failed to store spam memory: {e}", e=e)

    # Reset tracker for this user/channel
    dq.clear()
    _spam_tracker.pop(key, None)

    logger.info(
        "Spam detected: {user} in channel {ch} — muted {min}min",
        user=username, ch=channel_id, min=cfg.mute_minutes,
    )
    return True
```

- [ ] **Step 4: Integrate into handle_message()**

In `handle_message()`, right after the `channel_allowed` prelude block (after line 162) and before the `triggered` check (line 171), add:
```python
    # Spam detection — track all messages in allowed channels
    if channel_allowed and message.guild:
        if await _check_spam(bot, message):
            return
```

Modify the `is_muted` block (lines 216-219) to add anger delta:
```python
    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        if bot.config.discord.spam_detection.enabled:
            bot.emotion.apply_delta("anger", bot.config.discord.spam_detection.spam_anger_delta)
        return
```

- [ ] **Step 5: Export _spam_tracker for testing**

Make sure `_spam_tracker` and `_check_spam` are importable (they are module-level, so they're already importable).

- [ ] **Step 6: Run spam tests**

Run: `python -m pytest tests/test_spam_detection.py -v`
Expected: all 5 tests PASS

- [ ] **Step 7: Update make_bot() in existing test file**

In `tests/test_discord_handlers.py`, add to `make_bot()`:
```python
    bot.config.discord.spam_detection.enabled = False  # disable in legacy tests
```
This prevents any interference with existing tests.

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: all tests pass

- [ ] **Step 9: Commit**

```bash
git add bot/discord/handlers.py tests/test_spam_detection.py tests/test_discord_handlers.py
git commit -m "feat: spam detection with LLM warning, mute, memory, and anger escalation"
```

---

### Task 4: Dashboard admin — spam config API

**Files:**
- Modify: `bot/dashboard/routes/admin.py:113-125` (extend discord section in POST /config)
- Test: `tests/test_dashboard_routes.py` (add spam config test)

- [ ] **Step 1: Write failing test**

Add to `tests/test_dashboard_routes.py`:
```python
@pytest.mark.asyncio
async def test_update_spam_detection_config(client):
    resp = await client.post(
        "/api/admin/config",
        json={"discord": {"spam_detection": {
            "enabled": False,
            "max_messages": 15,
            "window_seconds": 60,
            "mute_minutes": 3,
            "spam_anger_delta": 0.1,
            "exempt_channels": [111, 222],
        }}},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
    cfg = client.app.state.wally.config
    assert cfg.discord.spam_detection.enabled is False
    assert cfg.discord.spam_detection.max_messages == 15
    assert cfg.discord.spam_detection.window_seconds == 60
    assert cfg.discord.spam_detection.exempt_channels == [111, 222]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_routes.py::test_update_spam_detection_config -v`
Expected: FAIL — the POST handler doesn't process `spam_detection` yet

- [ ] **Step 3: Add spam_detection handling in POST /config**

In `bot/dashboard/routes/admin.py`, inside the `if "discord" in body:` block (after line 124), add:
```python
        if "spam_detection" in d:
            sd = d["spam_detection"]
            spam = cfg.discord.spam_detection
            if "enabled" in sd:
                spam.enabled = bool(sd["enabled"])
            if "max_messages" in sd:
                val = int(sd["max_messages"])
                if not (3 <= val <= 50):
                    raise HTTPException(400, "max_messages must be 3-50")
                spam.max_messages = val
            if "window_seconds" in sd:
                val = int(sd["window_seconds"])
                if not (30 <= val <= 600):
                    raise HTTPException(400, "window_seconds must be 30-600")
                spam.window_seconds = val
            if "mute_minutes" in sd:
                val = int(sd["mute_minutes"])
                if not (1 <= val <= 60):
                    raise HTTPException(400, "mute_minutes must be 1-60")
                spam.mute_minutes = val
            if "spam_anger_delta" in sd:
                val = float(sd["spam_anger_delta"])
                if not (0.01 <= val <= 0.2):
                    raise HTTPException(400, "spam_anger_delta must be 0.01-0.2")
                spam.spam_anger_delta = val
            if "exempt_channels" in sd:
                spam.exempt_channels = [int(c) for c in sd["exempt_channels"]]
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_dashboard_routes.py::test_update_spam_detection_config -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add bot/dashboard/routes/admin.py tests/test_dashboard_routes.py
git commit -m "feat(dashboard): add spam detection config to admin API"
```

---

### Task 5: Dashboard UI — anti-spam settings section

**Files:**
- Modify: `bot/dashboard/static/app.js` (add anti-spam section in admin settings)

- [ ] **Step 1: Find the settings rendering section in app.js**

Search for existing Discord settings rendering (anger_trigger_threshold, timeout_minutes) to find where to add the new section.

- [ ] **Step 2: Add anti-spam section to the admin settings UI**

Add a "Anti-spam" card/section after the existing Discord settings, containing:
- Toggle for `enabled`
- Number input for `max_messages` (min 3, max 50)
- Number input for `window_seconds` (min 30, max 600)
- Number input for `mute_minutes` (min 1, max 60)
- Number input for `spam_anger_delta` (min 0.01, max 0.2, step 0.01)
- Text area or list for `exempt_channels`

Follow the existing glassmorphism style: `rgba(255,255,255,0.03)` backgrounds, `blur(10px)`, `12px` radius, subtle borders.

- [ ] **Step 3: Wire up load/save to existing config endpoints**

Load: In the config fetch handler, populate the anti-spam fields from `config.discord.spam_detection`.
Save: In the save handler, include `spam_detection` in the `discord` section of the POST body.

- [ ] **Step 4: Test manually in browser**

Open the dashboard, navigate to admin settings, verify:
- Anti-spam section appears with correct current values
- Toggling enabled/disabled works and persists after page reload
- Changing values and saving persists correctly

- [ ] **Step 5: Commit**

```bash
git add bot/dashboard/static/app.js
git commit -m "feat(dashboard): add anti-spam settings UI section"
```

---

### Task 6: Final integration test + cleanup

**Files:**
- Test: `tests/test_spam_detection.py` (add edge case tests)

- [ ] **Step 1: Add edge case tests**

```python
@pytest.mark.asyncio
async def test_spam_does_not_trigger_in_dms():
    """DMs should be excluded from spam detection."""
    bot = _make_spam_bot(max_messages=2)
    msg = _make_msg(content="wally hey")
    msg.guild = None  # DM
    msg.mentions = [bot.user]

    for _ in range(5):
        await handle_message(bot, msg)

    bot.db.add_timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_channels_have_separate_trackers():
    """Spam tracking is per-channel, not global per-user."""
    bot = _make_spam_bot(max_messages=3, window_seconds=60)

    for ch_id in [100, 200]:
        msg = _make_msg(content="wally hey", channel_id=ch_id)
        msg.mentions = [bot.user]
        # 2 messages per channel — below threshold of 3
        await handle_message(bot, msg)
        await handle_message(bot, msg)

    bot.db.add_timeout.assert_not_awaited()
```

- [ ] **Step 2: Run all spam tests**

Run: `python -m pytest tests/test_spam_detection.py -v`
Expected: all tests PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: all tests pass, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_spam_detection.py
git commit -m "test: add edge case tests for spam detection (DMs, multi-channel)"
```
