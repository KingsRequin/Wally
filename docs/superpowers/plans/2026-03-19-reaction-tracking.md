# Réactivité aux réactions post-Wally — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wally détecte les réactions positives à ses messages (emoji Discord, replies "mdr", messages Twitch dans la fenêtre) et booste sa joy proportionnellement.

**Architecture:** Nouveau module `ReactionTracker` qui centralise la logique. Discord : event `on_raw_reaction_add` + détection des replies. Twitch : fenêtre temporelle 120s. Paliers graduels : 1-2 réactions → +0.05 joy, 3-5 → +0.10, 6+ → +0.15.

**Tech Stack:** Python 3.11+, pytest, discord.py 2.x, loguru

**Spec:** `docs/superpowers/specs/2026-03-19-reaction-tracking-design.md`

---

### Task 1: ReactionTracker — module core + tests

**Files:**
- Create: `bot/core/reaction_tracker.py`
- Create: `tests/test_reaction_tracker.py`

- [ ] **Step 1: Créer les tests unitaires**

Créer `tests/test_reaction_tracker.py` :

```python
# tests/test_reaction_tracker.py
import time
from unittest.mock import MagicMock

import pytest

from bot.core.reaction_tracker import ReactionTracker


def make_emotion():
    engine = MagicMock()
    engine.apply_delta = MagicMock()
    return engine


# ── Tier logic ────────────────────────────────────────────────────────────

def test_tier_delta_first_reaction():
    """1 réaction → tier 1 → delta 0.05."""
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(1, 0)
    assert new_tier == 1
    assert delta == pytest.approx(0.05)


def test_tier_delta_escalation():
    """3 réactions → tier 2 → delta supplémentaire 0.05."""
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(3, 1)
    assert new_tier == 2
    assert delta == pytest.approx(0.05)


def test_tier_delta_max():
    """6 réactions → tier 3 → delta supplémentaire 0.05."""
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(6, 2)
    assert new_tier == 3
    assert delta == pytest.approx(0.05)


def test_tier_delta_same_tier_no_delta():
    """2 réactions, déjà tier 1 → pas de delta."""
    tracker = ReactionTracker(make_emotion())
    new_tier, delta = tracker._apply_tier_delta(2, 1)
    assert new_tier == 1
    assert delta == 0.0


# ── Discord reactions ─────────────────────────────────────────────────────

def test_discord_reaction_increments_and_applies_joy():
    """3 réactions positives → joy boostée deux fois (tier 1 + tier 2)."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "😂", is_bot=False)
    tracker.record_discord_reaction(12345, "🤣", is_bot=False)
    tracker.record_discord_reaction(12345, "🔥", is_bot=False)
    # 3 réactions : tier 1 at count 1 (+0.05), tier 2 at count 3 (+0.05)
    calls = emotion.apply_delta.call_args_list
    assert len(calls) == 2
    assert all(c.args == ("joy",) or c[0][0] == "joy" for c in calls)


def test_discord_reaction_ignores_unknown_message():
    """Réaction sur un message non tracké → rien."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.record_discord_reaction(99999, "😂", is_bot=False)
    emotion.apply_delta.assert_not_called()


def test_discord_reaction_ignores_negative_emoji():
    """👎 sur un message tracké → ignoré."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "👎", is_bot=False)
    emotion.apply_delta.assert_not_called()


def test_discord_reaction_ignores_bot():
    """Réaction d'un bot → ignorée."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reaction(12345, "😂", is_bot=True)
    emotion.apply_delta.assert_not_called()


# ── Discord replies ───────────────────────────────────────────────────────

def test_discord_reply_positive_keyword():
    """Reply contenant 'mdr' → compteur incrémenté."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reply(12345, "mdr trop bien", is_bot=False)
    assert emotion.apply_delta.call_count == 1


def test_discord_reply_no_keyword():
    """Reply sans mot-clé positif → ignoré."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(12345)
    tracker.record_discord_reply(12345, "ok merci", is_bot=False)
    emotion.apply_delta.assert_not_called()


# ── Twitch window ─────────────────────────────────────────────────────────

def test_twitch_window_active():
    """Message avec 'lol' dans la fenêtre → compteur incrémenté."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:channel1")
    tracker.check_twitch_message("twitch:channel1", "lol c'était drôle")
    assert emotion.apply_delta.call_count == 1


def test_twitch_window_expired():
    """Message après 120s → ignoré."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:channel1")
    # Forcer le timestamp dans le passé
    tracker._twitch_windows["twitch:channel1"].timestamp = time.time() - 130
    tracker.check_twitch_message("twitch:channel1", "lol")
    emotion.apply_delta.assert_not_called()


def test_twitch_window_reset_on_new_response():
    """Nouvelle réponse Wally → fenêtre reset, compteur à 0."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_twitch_response("twitch:ch")
    tracker.check_twitch_message("twitch:ch", "mdr")  # count=1, tier=1
    tracker.track_twitch_response("twitch:ch")  # reset
    assert tracker._twitch_windows["twitch:ch"].count == 0
    assert tracker._twitch_windows["twitch:ch"].last_applied_tier == 0


# ── Cleanup ───────────────────────────────────────────────────────────────

def test_cleanup_removes_old_entries():
    """Entries > 10 min supprimées."""
    emotion = make_emotion()
    tracker = ReactionTracker(emotion)
    tracker.track_discord_message(111)
    tracker._discord_messages[111].timestamp = time.time() - 700
    tracker.track_discord_message(222)  # triggers cleanup
    assert 111 not in tracker._discord_messages
    assert 222 in tracker._discord_messages
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `python3 -m pytest tests/test_reaction_tracker.py -v`
Expected: FAILED (module n'existe pas)

- [ ] **Step 3: Implémenter `bot/core/reaction_tracker.py`**

```python
# bot/core/reaction_tracker.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.core.emotion import EmotionEngine

TWITCH_WINDOW_SECONDS = 120
CLEANUP_AGE_SECONDS = 600

# (max_count_for_tier, cumulative_delta)
JOY_TIERS = [(2, 0.05), (5, 0.10), (float("inf"), 0.15)]

POSITIVE_KEYWORDS = {
    "mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣",
    "pog", "gg", "bien joué", "trop bon",
}

POSITIVE_EMOJIS = {
    "😂", "🤣", "❤️", "❤", "👍", "💀", "😭", "🔥", "👏",
}


@dataclass
class _DiscordReactionState:
    count: int = 0
    last_applied_tier: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class _TwitchWindow:
    timestamp: float = field(default_factory=time.time)
    count: int = 0
    last_applied_tier: int = 0


class ReactionTracker:
    def __init__(self, emotion: "EmotionEngine"):
        self._emotion = emotion
        self._discord_messages: dict[int, _DiscordReactionState] = {}
        self._twitch_windows: dict[str, _TwitchWindow] = {}

    # ── Tier logic ────────────────────────────────────────────────────────

    def _apply_tier_delta(self, count: int, last_tier: int) -> tuple[int, float]:
        """Retourne (new_tier, delta_to_apply) basé sur le count actuel."""
        current_tier = 0
        current_delta = 0.0
        for i, (max_count, cumulative) in enumerate(JOY_TIERS, 1):
            if count <= max_count:
                current_tier = i
                current_delta = cumulative
                break
        if current_tier <= last_tier:
            return last_tier, 0.0
        prev_delta = JOY_TIERS[last_tier - 1][1] if last_tier > 0 else 0.0
        return current_tier, current_delta - prev_delta

    def _maybe_apply(self, count: int, last_tier: int) -> int:
        """Applique le delta joy si changement de palier. Retourne le nouveau tier."""
        new_tier, delta = self._apply_tier_delta(count, last_tier)
        if delta > 0:
            self._emotion.apply_delta("joy", delta)
            logger.debug(
                "Reaction joy boost: count={c} tier={t} delta={d}",
                c=count, t=new_tier, d=delta,
            )
        return new_tier

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _cleanup(self) -> None:
        now = time.time()
        cutoff = now - CLEANUP_AGE_SECONDS
        stale = [mid for mid, s in self._discord_messages.items() if s.timestamp < cutoff]
        for mid in stale:
            del self._discord_messages[mid]
        stale_tw = [ch for ch, w in self._twitch_windows.items() if w.timestamp < cutoff]
        for ch in stale_tw:
            del self._twitch_windows[ch]

    # ── Discord ───────────────────────────────────────────────────────────

    def track_discord_message(self, message_id: int) -> None:
        self._cleanup()
        self._discord_messages[message_id] = _DiscordReactionState()

    def record_discord_reaction(
        self, message_id: int, emoji: str, is_bot: bool
    ) -> None:
        if is_bot:
            return
        state = self._discord_messages.get(message_id)
        if state is None:
            return
        if emoji not in POSITIVE_EMOJIS:
            return
        state.count += 1
        state.last_applied_tier = self._maybe_apply(state.count, state.last_applied_tier)

    def record_discord_reply(
        self, message_id: int, text: str, is_bot: bool
    ) -> None:
        if is_bot:
            return
        state = self._discord_messages.get(message_id)
        if state is None:
            return
        text_lower = text.lower()
        if not any(kw in text_lower for kw in POSITIVE_KEYWORDS):
            return
        state.count += 1
        state.last_applied_tier = self._maybe_apply(state.count, state.last_applied_tier)

    # ── Twitch ────────────────────────────────────────────────────────────

    def track_twitch_response(self, channel_id: str) -> None:
        self._cleanup()
        self._twitch_windows[channel_id] = _TwitchWindow()

    def check_twitch_message(self, channel_id: str, text: str) -> None:
        window = self._twitch_windows.get(channel_id)
        if window is None:
            return
        if time.time() - window.timestamp > TWITCH_WINDOW_SECONDS:
            return
        text_lower = text.lower()
        if not any(kw in text_lower for kw in POSITIVE_KEYWORDS):
            return
        window.count += 1
        window.last_applied_tier = self._maybe_apply(window.count, window.last_applied_tier)
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `python3 -m pytest tests/test_reaction_tracker.py -v`
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/core/reaction_tracker.py tests/test_reaction_tracker.py
git commit -m "feat(core): add ReactionTracker for post-Wally reaction detection"
```

---

### Task 2: Intégration Discord — bot.py + handlers.py

**Files:**
- Modify: `bot/discord/bot.py` — attribut + event handler
- Modify: `bot/discord/handlers.py` — track message_id, détecter replies, modifier `_send_in_parts`

- [ ] **Step 1: Ajouter `reaction_tracker = None` dans `WallyDiscord.__init__`**

Dans `bot/discord/bot.py`, après `self.dashboard_state = None` :

```python
self.reaction_tracker = None  # set by main.py after construction
```

- [ ] **Step 2: Ajouter l'event `on_raw_reaction_add`**

Dans `bot/discord/bot.py`, après `on_error` :

```python
async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
    if not self.reaction_tracker:
        return
    if payload.user_id == self.user.id:
        return
    member = payload.member
    is_bot = member.bot if member else False
    self.reaction_tracker.record_discord_reaction(
        payload.message_id, str(payload.emoji), is_bot,
    )
```

- [ ] **Step 3: Modifier `_send_in_parts` pour retourner le message_id**

Dans `bot/discord/handlers.py`, modifier `_send_in_parts` pour retourner le message_id du premier message :

Changer la signature et le return :
```python
async def _send_in_parts(message: discord.Message, text: str) -> int | None:
```

Après `await message.reply(groups[0])`, capturer le message :
```python
    first_msg = await message.reply(groups[0])
    for group in groups[1:]:
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await message.channel.send(group)
    return first_msg.id
```

- [ ] **Step 4: Dans `_respond`, tracker le message_id**

Dans `_respond()`, remplacer `await _send_in_parts(message, reply)` par :

```python
        reply_msg_id = await _send_in_parts(message, reply)
        if reply_msg_id and getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_discord_message(reply_msg_id)
```

- [ ] **Step 5: Dans `handle_message`, détecter les replies positifs**

Dans `handle_message()`, après le bloc `bot.memory.append_prelude(...)` et avant le trigger check, ajouter :

```python
    # Reaction tracking: detect positive replies to Wally's messages
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker and message.reference and message.reference.message_id:
        tracker.record_discord_reply(
            message.reference.message_id, message.content, message.author.bot,
        )
```

- [ ] **Step 6: Lancer les tests**

Run: `python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5`
Expected: ALL PASSED

- [ ] **Step 7: Commit**

```bash
git add bot/discord/bot.py bot/discord/handlers.py
git commit -m "feat(discord): integrate ReactionTracker — emoji reactions + positive replies"
```

---

### Task 3: Intégration Twitch + main.py

**Files:**
- Modify: `bot/twitch/handlers.py` — track réponse + scanner fenêtre
- Modify: `bot/main.py` — créer et injecter ReactionTracker

- [ ] **Step 1: Modifier `bot/twitch/handlers.py`**

Au début de `handle_message()`, après le bloc `bot.session_manager.record_message(...)` et avant le trigger check, ajouter :

```python
    # Reaction tracking: scan for positive reactions in Twitch window
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker:
        tracker.check_twitch_message(channel_id, content)
```

Après l'envoi de la réponse (après `bot.set_cooldown(user_id)` et les `append_message`), ajouter :

```python
        if getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_twitch_response(channel_id)
```

- [ ] **Step 2: Modifier `bot/main.py`**

Ajouter l'import et la création du tracker. Trouver l'endroit où les services sont créés (après `emotion = EmotionEngine(...)`) et ajouter :

```python
from bot.core.reaction_tracker import ReactionTracker
reaction_tracker = ReactionTracker(emotion)
```

Après la création de `discord_bot` et `twitch_bot`, injecter :

```python
discord_bot.reaction_tracker = reaction_tracker
twitch_bot.reaction_tracker = reaction_tracker
```

- [ ] **Step 3: Lancer toute la suite de tests**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add bot/twitch/handlers.py bot/main.py
git commit -m "feat: integrate ReactionTracker in Twitch handlers and main.py wiring"
```
