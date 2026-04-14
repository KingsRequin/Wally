# Bot Structure Refactor — Twitch & Discord Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganiser `bot/twitch/` et `bot/discord/` en sous-dossiers `commands/` et `events/` pour isoler les responsabilités, sans changer aucun comportement.

**Architecture:** Chaque plateforme obtient un dossier `commands/` (handlers `!`) et un dossier `events/` (événements plateforme). Le pipeline LLM principal reste dans `handlers.py`. Les imports existants dans `main.py` et `bot.py` sont mis à jour pour pointer vers les nouveaux chemins.

**Tech Stack:** Python 3.11+, discord.py 2.x, twitchio 2.x, asyncio, loguru

---

## File Map

### Nouveaux fichiers créés

| Fichier | Contenu |
|---|---|
| `bot/twitch/commands/__init__.py` | `dispatch_command(bot, payload, ...) → bool` |
| `bot/twitch/commands/code.py` | `_daily_codes` state + `handle_code_command()` |
| `bot/twitch/commands/mood.py` | `handle_mood_command()` |
| `bot/twitch/events/__init__.py` | `register_events()` + `start_eventsub_client()` |
| `bot/twitch/events/models.py` | `_ChatBadge`, `ChatMessageData`, `_ChatMessageText` |
| `bot/twitch/events/social.py` | follow/sub/resub/gift_sub/cheer/raid handlers + helpers |
| `bot/discord/events/__init__.py` | `register_events(bot)` |
| `bot/discord/events/reactions.py` | `on_raw_reaction_add`, `on_reaction_add` |
| `bot/discord/events/voice.py` | `on_voice_state_update` |
| `bot/discord/events/presence.py` | `on_presence_update` |

### Fichiers modifiés

| Fichier | Changement |
|---|---|
| `bot/twitch/handlers.py` | Supprime bloc `!code`, `!mood`, overlay dispatch → appelle `dispatch_command()` |
| `bot/twitch/events.py` | **Supprimé** — remplacé par `bot/twitch/events/` |
| `bot/discord/bot.py` | Supprime handlers inline → appelle `register_events(self)` dans `setup_hook` |

---

## Chantier A — Twitch Events

### Task 1 : Créer `bot/twitch/events/models.py`

**Files:**
- Create: `bot/twitch/events/__init__.py` (vide pour l'instant)
- Create: `bot/twitch/events/models.py`

- [ ] **Step 1 : Créer le dossier et `__init__.py` vide**

```bash
mkdir -p /opt/stacks/wally-ai/bot/twitch/events
touch /opt/stacks/wally-ai/bot/twitch/events/__init__.py
```

- [ ] **Step 2 : Créer `bot/twitch/events/models.py`**

Copier exactement les trois classes depuis `bot/twitch/events.py` (lignes 209–241) :

```python
# bot/twitch/events/models.py
from __future__ import annotations


class _ChatBadge:
    """Wraps an EventSub badge entry.

    EventSub badge format: {"set_id": "moderator", "id": "1", "info": ""}
    The type identifier is in `set_id` ("moderator", "broadcaster", "subscriber", "vip", "bot"…).
    We expose it as `.id` so existing callers (b.id if hasattr(b,'id') else str(b)) work without change.
    """

    __slots__ = ("id", "set_id")

    def __init__(self, data: dict):
        self.set_id: str = data.get("set_id", "")
        self.id: str = self.set_id  # callers check b.id for type names


class ChatMessageData:
    """Minimal data model for channel.chat.message EventSub notifications.

    Registered into twitchio v2's SubscriptionTypes at runtime in
    start_eventsub_client() since twitchio v2 does not natively support
    channel.chat.message.

    Attributes:
      chatter.id / chatter.name — chatter_user_id / chatter_user_login
      message.text              — message.text
      broadcaster.name          — broadcaster_user_login
      badges                    — list[_ChatBadge] from top-level "badges" array
    """

    __slots__ = "chatter", "message", "broadcaster", "message_id", "badges"

    def __init__(self, client, data: dict):
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )
        self.message_id: str = data.get("message_id", "")
        self.badges: list[_ChatBadge] = [
            _ChatBadge(b) for b in data.get("badges", [])
        ]


class _ChatMessageText:
    __slots__ = ("text",)

    def __init__(self, data: dict):
        self.text: str = data["text"]
```

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.events.models import ChatMessageData, _ChatBadge; print('OK')"
```

Attendu : `OK`

---

### Task 2 : Créer `bot/twitch/events/social.py`

**Files:**
- Create: `bot/twitch/events/social.py`

- [ ] **Step 1 : Créer `bot/twitch/events/social.py`**

Copier depuis `bot/twitch/events.py` les helpers et les event handlers (lignes 17–90 + `register_events` + `_generate_and_send`). Mettre à jour l'import de `ChatMessageData` :

```python
# bot/twitch/events/social.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

from bot.twitch.handlers import handle_message, _fire

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


def _check_peak(bot, emotion: str, old_val: float, delta: float, username: str = "", event_name: str = ""):
    """Fire-and-forget peak check for Twitch events."""
    import inspect
    new_val = min(1.0, old_val + delta)
    if hasattr(bot.emotion, '_maybe_log_peak'):
        coro = bot.emotion._maybe_log_peak(
            emotion, old_val, new_val,
            trigger_user=username,
            trigger_message=f"[Twitch {event_name}]",
            channel_id="", platform="twitch",
        )
        if inspect.iscoroutine(coro):
            _fire(coro)


_recent_follows: list[float] = []
_FOLLOW_BURST_WINDOW = 60.0
_FOLLOW_BURST_THRESHOLD = 5


def _check_follow_burst() -> bool:
    import time as _time
    now = _time.time()
    cutoff = now - _FOLLOW_BURST_WINDOW
    _recent_follows[:] = [t for t in _recent_follows if t >= cutoff]
    _recent_follows.append(now)
    return len(_recent_follows) >= _FOLLOW_BURST_THRESHOLD


def _bits_joy(amount: int) -> float:
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
    try:
        from bot.core.prompts import PromptBuilder
        from bot.twitch.handlers import _build_situation

        formatted = PromptBuilder.format_event_message(template, **kwargs)
        situation = _build_situation(bot, channel_name)
        system = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
        event_user_id = f"twitch:{kwargs.get('username', '')}" if kwargs.get('username') else None
        reply = await bot.llm.complete(
            system,
            [{"role": "user", "content": f"Réagis à cet événement Twitch : {formatted}"}],
            purpose="twitch_event",
            user_id=event_user_id,
        )
        if len(reply) > 480:
            reply = reply[:477] + "..."
        await bot.twitch_api.send_message(text=reply)
    except Exception as e:
        logger.error("Twitch event send error: {e}", e=e)


def register_events(bot: "WallyTwitch") -> None:
    """Register EventSub WebSocket social event handlers on the bot instance."""

    @bot.event()
    async def event_eventsub_notification_followV2(payload) -> None:
        cfg = bot.config.twitch_events.get("follow")
        if not cfg or not cfg.active:
            return
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.1)
        _check_peak(bot, "joy", old_joy, 0.1, username=payload.data.user.name, event_name="follow")
        if _check_follow_burst():
            old_curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            bot.emotion.apply_delta("curiosity", 0.2)
            _check_peak(bot, "curiosity", old_curiosity, 0.2, username=payload.data.user.name, event_name="follow_burst")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription(payload) -> None:
        cfg = bot.config.twitch_events.get("sub")
        if not cfg or not cfg.active:
            return
        if payload.data.is_gift:
            return
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.4)
        _check_peak(bot, "joy", old_joy, 0.4, username=payload.data.user.name, event_name="subscribe")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_message(payload) -> None:
        cfg = bot.config.twitch_events.get("resub")
        if not cfg or not cfg.active:
            return
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.3)
        _check_peak(bot, "joy", old_joy, 0.3, username=payload.data.user.name, event_name="resub")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=payload.data.user.name, amount=0,
            months=payload.data.cumulative_months, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_gift(payload) -> None:
        cfg = bot.config.twitch_events.get("gift_sub")
        if not cfg or not cfg.active:
            return
        gifter = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", 0.5)
        _check_peak(bot, "joy", old_joy, 0.5, username=gifter, event_name="gift_sub")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=gifter,
            amount=payload.data.total,
            months=0,
            raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_subscription_end(payload) -> None:
        logger.debug("Sub end: {user}", user=payload.data.user.name)

    @bot.event()
    async def event_eventsub_notification_cheer(payload) -> None:
        cfg = bot.config.twitch_events.get("bits")
        if not cfg or not cfg.active:
            return
        delta = _bits_joy(payload.data.bits)
        username = "Anonyme" if payload.data.is_anonymous else payload.data.user.name
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", delta)
        _check_peak(bot, "joy", old_joy, delta, username=username, event_name="bits")
        await _generate_and_send(
            bot, payload.data.broadcaster.name, cfg.message,
            username=username, amount=payload.data.bits, months=0, raiders_count=0,
        )

    @bot.event()
    async def event_eventsub_notification_raid(payload) -> None:
        cfg = bot.config.twitch_events.get("raid")
        if not cfg or not cfg.active:
            return
        viewers = payload.data.viewer_count
        joy_spike = min(viewers / 50, 0.9)
        old_joy = bot.emotion.get_state().get("joy", 0.0)
        bot.emotion.apply_delta("joy", joy_spike)
        _check_peak(bot, "joy", old_joy, joy_spike, username=payload.data.raider.name, event_name="raid")
        if viewers >= 50:
            curiosity_spike = min(viewers / 100, 0.5)
            old_curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            bot.emotion.apply_delta("curiosity", curiosity_spike)
            _check_peak(bot, "curiosity", old_curiosity, curiosity_spike, username=payload.data.raider.name, event_name="raid_massive")
        channel_name = payload.data.reciever.name
        await _generate_and_send(
            bot, channel_name, cfg.message,
            username=payload.data.raider.name, amount=0,
            months=0, raiders_count=payload.data.viewer_count,
        )

    @bot.event()
    async def event_eventsub_notification_channel_chat_message(payload) -> None:
        await handle_message(bot, payload.data)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.events.social import register_events; print('OK')"
```

Attendu : `OK`

---

### Task 3 : Créer `bot/twitch/events/__init__.py`

**Files:**
- Modify: `bot/twitch/events/__init__.py`

- [ ] **Step 1 : Écrire `__init__.py`**

Copier `start_eventsub_client()` et `_subscribe_chat()` depuis `bot/twitch/events.py` (lignes 244–373), en mettant à jour l'import de `ChatMessageData` :

```python
# bot/twitch/events/__init__.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

from bot.twitch.events.models import ChatMessageData
from bot.twitch.events.social import register_events  # re-export

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def start_eventsub_client(bot: "WallyTwitch") -> None:
    """Create an EventSub WebSocket client and subscribe to channel events."""
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

        if "channel.chat.message" not in SubscriptionTypes._name_map:
            SubscriptionTypes._name_map["channel.chat.message"] = "channel_chat_message"
            SubscriptionTypes._type_map["channel.chat.message"] = ChatMessageData

        client = eventsub.EventSubWSClient(bot)

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
            await asyncio.sleep(1.5)

        for guest_name in bot.config.twitch.guest_channels:
            guest_id = await bot.twitch_api.get_broadcaster_id(guest_name)
            if guest_id:
                bot._channel_ids[guest_name] = guest_id
                try:
                    await _subscribe_chat(client, guest_id, bot_id, bot_token)
                    logger.info("EventSub subscribed: chat guest {name}", name=guest_name)
                except Exception as exc:
                    logger.warning(
                        "EventSub guest chat failed [{name}]: {e}", name=guest_name, e=exc
                    )
            else:
                logger.warning(
                    "Chaîne invitée introuvable ou API indisponible: {name}", name=guest_name
                )
            await asyncio.sleep(0.5)

        bot._eventsub_client = client
        logger.info(
            "EventSub WebSocket client active (broadcaster_id={bid})", bid=broadcaster_id
        )

    except Exception as exc:
        logger.error("EventSub client setup failed: {e}", e=exc)


async def _subscribe_chat(client, broadcaster_id: str, bot_id: str, token: str):
    from twitchio.ext.eventsub.websocket import _Subscription

    sub = _Subscription(
        ("channel.chat.message", 1, ChatMessageData),
        {"broadcaster_user_id": broadcaster_id, "user_id": bot_id},
        token,
    )
    await client._assign_subscription(sub)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.events import start_eventsub_client, register_events; print('OK')"
```

Attendu : `OK`

---

### Task 4 : Mettre à jour les imports dans `bot/twitch/bot.py`

**Files:**
- Modify: `bot/twitch/bot.py`

- [ ] **Step 1 : Remplacer les imports dans `bot.py`**

Dans `bot/twitch/bot.py`, chercher toutes les occurrences de `from bot.twitch.events import` et remplacer par le nouveau chemin :

Ligne ~97 dans `start()` :
```python
# AVANT
from bot.twitch.events import start_eventsub_client

# APRÈS
from bot.twitch.events import start_eventsub_client  # inchangé — re-exporté par __init__
```

Ligne ~359 dans `_restart_eventsub()` :
```python
# AVANT
from bot.twitch.events import start_eventsub_client

# APRÈS
from bot.twitch.events import start_eventsub_client  # inchangé — re-exporté par __init__
```

Ces imports ne changent pas car `start_eventsub_client` est re-exporté depuis `bot/twitch/events/__init__.py`. Aucune modification nécessaire dans `bot.py`.

- [ ] **Step 2 : Vérifier le démarrage**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.bot import WallyTwitch; print('OK')"
```

Attendu : `OK`

---

### Task 5 : Supprimer `bot/twitch/events.py`

**Files:**
- Delete: `bot/twitch/events.py`

- [ ] **Step 1 : Vérifier qu'aucun import direct ne pointe encore vers l'ancien fichier**

```bash
grep -r "from bot.twitch.events import\|import bot.twitch.events" /opt/stacks/wally-ai/bot /opt/stacks/wally-ai/tests 2>/dev/null
```

Vérifier que tous les résultats pointent vers `bot.twitch.events` (le package, pas le module fichier). Si un import pointe vers `_ChatBadge`, `ChatMessageData`, ou `register_events` directement, le mettre à jour vers `bot.twitch.events.models` ou `bot.twitch.events.social`.

- [ ] **Step 2 : Supprimer l'ancien fichier**

```bash
rm /opt/stacks/wally-ai/bot/twitch/events.py
```

- [ ] **Step 3 : Vérifier qu'aucune ImportError**

```bash
cd /opt/stacks/wally-ai && python -c "
from bot.twitch.events import start_eventsub_client, register_events
from bot.twitch.events.models import ChatMessageData, _ChatBadge
from bot.twitch.events.social import register_events
print('OK')
"
```

Attendu : `OK`

- [ ] **Step 4 : Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/twitch/events/
git rm bot/twitch/events.py
git commit -m "refactor(twitch): split events.py → events/ package (models + social)"
```

---

## Chantier B — Twitch Commands

### Task 6 : Créer `bot/twitch/commands/mood.py`

**Files:**
- Create: `bot/twitch/commands/__init__.py`
- Create: `bot/twitch/commands/mood.py`

- [ ] **Step 1 : Créer le dossier et `__init__.py` temporaire vide**

```bash
mkdir -p /opt/stacks/wally-ai/bot/twitch/commands
touch /opt/stacks/wally-ai/bot/twitch/commands/__init__.py
```

- [ ] **Step 2 : Créer `bot/twitch/commands/mood.py`**

Extraire le bloc `!mood` de `bot/twitch/handlers.py` (lignes ~152–165) :

```python
# bot/twitch/commands/mood.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def handle_mood_command(bot: "WallyTwitch", channel_name: str) -> None:
    """Envoie l'état émotionnel courant dans le chat Twitch."""
    state = bot.emotion.get_state()
    emojis = {"anger": "😤", "joy": "😄", "sadness": "😢", "curiosity": "🤔", "boredom": "😑"}
    labels = {"anger": "Colère", "joy": "Joie", "sadness": "Tristesse", "curiosity": "Curiosité", "boredom": "Ennui"}
    parts = [
        f"{emojis[e]} {labels[e]} {int(state[e]*100)}%"
        for e in ("anger", "joy", "sadness", "curiosity", "boredom")
    ]
    mood_text = "Humeur de Wally — " + " | ".join(parts)

    if channel_name in bot._channel_ids:
        irc_channel = bot.get_channel(channel_name)
        if irc_channel:
            await irc_channel.send(mood_text)
    else:
        await bot.twitch_api.send_message(text=mood_text)
```

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.commands.mood import handle_mood_command; print('OK')"
```

Attendu : `OK`

---

### Task 7 : Créer `bot/twitch/commands/code.py`

**Files:**
- Create: `bot/twitch/commands/code.py`

- [ ] **Step 1 : Créer `bot/twitch/commands/code.py`**

Extraire le bloc `!code` de `bot/twitch/handlers.py` (lignes ~109–154). Le state `_daily_codes` déménage ici :

```python
# bot/twitch/commands/code.py
from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# État quotidien en mémoire — { channel_name: {"code": str|None, "date": "YYYY-MM-DD"} }
_daily_codes: dict[str, dict] = {}


def _code_display_msg(code: str) -> str:
    return (
        f"ON DIT BONJOUR AVANT DE METTRE LE CODE — "
        f"Le code est {code} — RAPPEL : si votre niveau est trop élevé "
        "donnez-vous des défis ou lâchez cette vilaine manette, "
        "on est pas là pour rouler sur la commu."
    )


async def handle_code_command(
    bot: "WallyTwitch",
    channel_name: str,
    author: str,
    args: str,
    badges: list,
) -> None:
    """Gère la commande !code — définir ou afficher le code du jour."""
    today = str(date.today())
    db_key = f"twitch_code:{channel_name}"

    # Premier accès après (re)démarrage : charger depuis la DB
    if channel_name not in _daily_codes:
        try:
            raw = await bot.db.get_persistent_note(db_key)
            if raw:
                _daily_codes[channel_name] = json.loads(raw)
            else:
                _daily_codes[channel_name] = {"code": None, "date": today}
        except Exception:
            _daily_codes[channel_name] = {"code": None, "date": today}

    state = _daily_codes[channel_name]

    # Reset quotidien
    if state["date"] != today:
        state["code"] = None
        state["date"] = today
        await bot.db.upsert_persistent_note(db_key, json.dumps(state))

    if args:
        # Définir le code — réservé aux mods et au broadcaster
        badge_ids = {b.id if hasattr(b, "id") else str(b) for b in badges}
        is_privileged = bool(badge_ids & {"moderator", "broadcaster"})
        if not is_privileged:
            code_msg = "Seuls les modérateurs peuvent définir le code. LUL"
        else:
            state["code"] = args
            state["date"] = today
            await bot.db.upsert_persistent_note(db_key, json.dumps(state))
            code_msg = _code_display_msg(args)
            logger.info("!code défini par {user} sur {ch} : {code}", user=author, ch=channel_name, code=args)
    else:
        if state["code"]:
            code_msg = _code_display_msg(state["code"])
        else:
            code_msg = "Pas de code pour le moment, rendez-vous samedi matin pour y participer !"

    if channel_name in bot._channel_ids:
        irc_channel = bot.get_channel(channel_name)
        if irc_channel:
            await irc_channel.send(code_msg)
    else:
        await bot.twitch_api.send_message(text=code_msg)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.commands.code import handle_code_command; print('OK')"
```

Attendu : `OK`

---

### Task 8 : Créer `bot/twitch/commands/__init__.py` avec le dispatcher

**Files:**
- Modify: `bot/twitch/commands/__init__.py`

- [ ] **Step 1 : Écrire le dispatcher**

```python
# bot/twitch/commands/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.twitch.commands.code import handle_code_command
from bot.twitch.commands.mood import handle_mood_command

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch


async def dispatch_command(
    bot: "WallyTwitch",
    payload,
    content: str,
    author: str,
    channel_name: str,
) -> bool:
    """Tente de matcher une commande !. Retourne True si une commande a été traitée."""
    content_stripped = content.strip()
    content_lower = content_stripped.lower()

    # Overlay image command
    overlay_cfg = bot.config.overlay_image
    if overlay_cfg.enabled and content_lower == overlay_cfg.command.lower():
        # Délégué à handlers.py via import local pour éviter la circularité
        from bot.twitch.handlers import _fire, _announce_overlay_image
        ds = getattr(bot, "dashboard_state", None)
        if ds is not None:
            image = await bot.db.get_random_gallery_image(overlay_cfg.random_filter)
            if image:
                img_payload = {
                    "image_url": f"/api/public/gallery/{image['id']}/image",
                    "title": image.get("title") or "",
                    "username": image["username"],
                    "display_duration": overlay_cfg.display_duration,
                    "animation_in": overlay_cfg.animation_in,
                    "animation_out": overlay_cfg.animation_out,
                    "animation_duration": overlay_cfg.animation_duration,
                }
                channel_id = f"twitch:{channel_name}"
                _fire(_announce_overlay_image(bot, channel_name, channel_id, image, ds, img_payload))
        return True

    if content_lower == "!mood":
        await handle_mood_command(bot, channel_name)
        return True

    if content_lower.startswith("!code"):
        args = content_stripped[len("!code"):].strip()
        badges = getattr(payload, "badges", []) or []
        await handle_code_command(bot, channel_name, author, args, badges)
        return True

    return False
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.commands import dispatch_command; print('OK')"
```

Attendu : `OK`

---

### Task 9 : Mettre à jour `bot/twitch/handlers.py`

**Files:**
- Modify: `bot/twitch/handlers.py`

- [ ] **Step 1 : Ajouter l'import du dispatcher en tête du fichier**

Après la ligne `from bot.discord.handlers import ...` ajouter :

```python
from bot.twitch.commands import dispatch_command
```

- [ ] **Step 2 : Supprimer `_daily_codes` du module-level**

Supprimer la ligne :
```python
# !code command state — { channel_name: {"code": str|None, "date": "YYYY-MM-DD"} }
_daily_codes: dict[str, dict] = {}
```

- [ ] **Step 3 : Remplacer les blocs overlay + !code + !mood par un appel unique**

Dans `handle_message`, remplacer les trois blocs (overlay ~lignes 89–107, `!code` ~lignes 109–154, `!mood` ~lignes 152–165) par :

```python
    # Dispatch commandes ! (overlay, !mood, !code, …)
    if await dispatch_command(bot, payload, content, author, channel_name):
        return
```

- [ ] **Step 4 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.twitch.handlers import handle_message; print('OK')"
```

Attendu : `OK`

- [ ] **Step 5 : Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/twitch/commands/
git add bot/twitch/handlers.py
git commit -m "refactor(twitch): extract !commands to commands/ package with dispatcher"
```

---

## Chantier C — Discord Events

### Task 10 : Créer `bot/discord/events/reactions.py`

**Files:**
- Create: `bot/discord/events/__init__.py` (vide)
- Create: `bot/discord/events/reactions.py`

- [ ] **Step 1 : Créer le dossier**

```bash
mkdir -p /opt/stacks/wally-ai/bot/discord/events
touch /opt/stacks/wally-ai/bot/discord/events/__init__.py
```

- [ ] **Step 2 : Créer `bot/discord/events/reactions.py`**

Extraire `on_raw_reaction_add` et `on_reaction_add` depuis `bot/discord/bot.py` (lignes 105–132) :

```python
# bot/discord/events/reactions.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        if not bot.reaction_tracker:
            return
        if payload.user_id == bot.user.id:
            return
        member = payload.member
        is_bot = member.bot if member else False
        bot.reaction_tracker.record_discord_reaction(
            payload.message_id, str(payload.emoji), is_bot,
        )

    @bot.event
    async def on_reaction_add(reaction, user) -> None:
        if user.bot or not bot.social:
            return
        author = reaction.message.author
        if author is None:
            return
        if author != user:
            bot.social.on_reaction(user.display_name, author.display_name)
```

- [ ] **Step 3 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.discord.events.reactions import register; print('OK')"
```

Attendu : `OK`

---

### Task 11 : Créer `bot/discord/events/voice.py`

**Files:**
- Create: `bot/discord/events/voice.py`

- [ ] **Step 1 : Créer `bot/discord/events/voice.py`**

Extraire `on_voice_state_update` depuis `bot/discord/bot.py` (lignes 116–123) :

```python
# bot/discord/events/voice.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_voice_state_update(member, before, after) -> None:
        if member.bot or not bot.social:
            return
        if before.channel != after.channel:
            if before.channel:
                bot.social.on_voice_leave(before.channel.id, member.id, member.display_name)
            if after.channel:
                bot.social.on_voice_join(after.channel.id, member.id, member.display_name)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.discord.events.voice import register; print('OK')"
```

Attendu : `OK`

---

### Task 12 : Créer `bot/discord/events/presence.py`

**Files:**
- Create: `bot/discord/events/presence.py`

- [ ] **Step 1 : Créer `bot/discord/events/presence.py`**

Extraire `on_presence_update` depuis `bot/discord/bot.py` (lignes 134–143) :

```python
# bot/discord/events/presence.py
from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_presence_update(before, after) -> None:
        if after.bot or not bot.social or not after.guild:
            return
        before_games = {a.name for a in (before.activities or []) if isinstance(a, discord.Game)}
        after_games = {a.name for a in (after.activities or []) if isinstance(a, discord.Game)}
        for game in after_games - before_games:
            bot.social.on_game_start(after.display_name, game)
        for game in before_games - after_games:
            bot.social.on_game_stop(after.display_name, game)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.discord.events.presence import register; print('OK')"
```

Attendu : `OK`

---

### Task 13 : Créer `bot/discord/events/__init__.py`

**Files:**
- Modify: `bot/discord/events/__init__.py`

- [ ] **Step 1 : Écrire `__init__.py`**

```python
# bot/discord/events/__init__.py
from __future__ import annotations

from typing import TYPE_CHECKING

from bot.discord.events import reactions, voice, presence

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord


def register_events(bot: "WallyDiscord") -> None:
    """Enregistre tous les gateway event handlers Discord sur le bot."""
    reactions.register(bot)
    voice.register(bot)
    presence.register(bot)
```

- [ ] **Step 2 : Vérifier l'import**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.discord.events import register_events; print('OK')"
```

Attendu : `OK`

---

### Task 14 : Mettre à jour `bot/discord/bot.py`

**Files:**
- Modify: `bot/discord/bot.py`

- [ ] **Step 1 : Ajouter l'import en tête du fichier**

Après `from loguru import logger`, ajouter :

```python
from bot.discord.events import register_events
```

- [ ] **Step 2 : Appeler `register_events` dans `setup_hook`**

À la fin de `setup_hook`, avant le bloc de sync des slash commands, ajouter :

```python
        register_events(self)
```

- [ ] **Step 3 : Supprimer les 5 méthodes extraites**

Supprimer de la classe `WallyDiscord` les méthodes :
- `on_raw_reaction_add` (lignes ~105–114)
- `on_voice_state_update` (lignes ~116–123)
- `on_reaction_add` (lignes ~125–132)
- `on_presence_update` (lignes ~134–143)
- `on_error` (lignes ~145–146)

Garder uniquement `__init__`, `setup_hook`, et `on_ready`.

**Note :** `on_error` n'est pas extrait dans un fichier dédié car c'est une ligne. Le conserver directement dans `setup_hook` via `bot.add_listener` ou le laisser dans `bot.py`. Option la plus simple : le laisser dans `bot.py`.

- [ ] **Step 4 : Vérifier**

```bash
cd /opt/stacks/wally-ai && python -c "from bot.discord.bot import WallyDiscord; print('OK')"
```

Attendu : `OK`

- [ ] **Step 5 : Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/discord/events/
git add bot/discord/bot.py
git commit -m "refactor(discord): extract gateway events to events/ package"
```

---

## Chantier D — Vérification finale

### Task 15 : Build Docker et smoke test

- [ ] **Step 1 : Build**

```bash
cd /opt/stacks/wally-ai && docker compose build --no-cache wally 2>&1 | tail -10
```

Attendu : `Image wally-ai-wally Built`

- [ ] **Step 2 : Up**

```bash
docker compose up -d wally 2>&1
```

- [ ] **Step 3 : Vérifier les logs de démarrage**

```bash
docker logs wally-bot 2>&1 | tail -20
```

Attendu : pas d'ImportError ni de traceback. Présence de `Discord bot ready` et/ou `Twitch bot token valid`.

- [ ] **Step 4 : Commit final si tout est OK**

```bash
cd /opt/stacks/wally-ai
git log --oneline -5
```

---

## Structure finale attendue

```
bot/
├── discord/
│   ├── bot.py              — WallyDiscord : __init__, setup_hook, on_ready, on_error
│   ├── handlers.py         — pipeline LLM principal
│   ├── social.py           — inchangé
│   ├── commands/           — slash commands (inchangé)
│   └── events/
│       ├── __init__.py     — register_events(bot)
│       ├── reactions.py    — on_raw_reaction_add, on_reaction_add
│       ├── voice.py        — on_voice_state_update
│       └── presence.py     — on_presence_update
└── twitch/
    ├── bot.py              — inchangé
    ├── handlers.py         — pipeline LLM (appelle dispatch_command)
    ├── api.py              — inchangé
    ├── token_manager.py    — inchangé
    ├── commands/
    │   ├── __init__.py     — dispatch_command()
    │   ├── code.py         — !code
    │   └── mood.py         — !mood
    └── events/
        ├── __init__.py     — start_eventsub_client()
        ├── models.py       — ChatMessageData, _ChatBadge
        └── social.py       — follow/sub/bits/raid + register_events()
```
