# Twitch Commands Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter des tests unitaires pour `bot/twitch/commands/code.py` et `bot/twitch/commands/mood.py`.

**Architecture:** Tests isolés avec mocks AsyncMock sur `bot.db`, `bot.emotion`, `bot.twitch_api`, `bot._channel_ids`. Pas de dépendance Docker ni Qdrant.

**Tech Stack:** pytest, pytest-asyncio, unittest.mock

---

## File Map

| Fichier | Action |
|---|---|
| `tests/test_twitch_commands_code.py` | Créer — 8 tests pour handle_code_command |
| `tests/test_twitch_commands_mood.py` | Créer — 4 tests pour handle_mood_command |

---

### Task 1 : Tests pour `handle_mood_command`

**Files:**
- Create: `tests/test_twitch_commands_mood.py`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_twitch_commands_mood.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def make_bot(channel_ids=None):
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.2, "joy": 0.5, "sadness": 0.1, "curiosity": 0.3, "boredom": 0.0,
    }
    bot._channel_ids = channel_ids or {}
    bot.twitch_api.send_message = AsyncMock()
    # IRC channel mock
    irc_channel = MagicMock()
    irc_channel.send = AsyncMock()
    bot.get_channel.return_value = irc_channel
    return bot


@pytest.mark.asyncio
async def test_mood_sends_via_helix_on_home_channel():
    """Sur la chaîne home (pas dans _channel_ids), envoi via Helix API."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={})
    await handle_mood_command(bot, "streamer")
    bot.twitch_api.send_message.assert_awaited_once()
    sent_text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Wally" in sent_text
    assert "Joie" in sent_text
    assert "50%" in sent_text


@pytest.mark.asyncio
async def test_mood_sends_via_irc_on_guest_channel():
    """Sur une chaîne invitée (dans _channel_ids), envoi via IRC."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={"guestchan": "456"})
    await handle_mood_command(bot, "guestchan")
    bot.get_channel.assert_called_once_with("guestchan")
    bot.get_channel.return_value.send.assert_awaited_once()
    bot.twitch_api.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_mood_message_contains_all_five_emotions():
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot()
    await handle_mood_command(bot, "streamer")
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    for label in ("Colère", "Joie", "Tristesse", "Curiosité", "Ennui"):
        assert label in text, f"Label '{label}' manquant dans: {text}"


@pytest.mark.asyncio
async def test_mood_irc_channel_none_does_not_crash():
    """Si get_channel retourne None (IRC non connecté), pas de crash."""
    from bot.twitch.commands.mood import handle_mood_command
    bot = make_bot(channel_ids={"guestchan": "456"})
    bot.get_channel.return_value = None
    await handle_mood_command(bot, "guestchan")
    # Pas d'exception = succès
```

- [ ] **Step 2 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python3 -m pytest tests/test_twitch_commands_mood.py -v 2>&1 | tail -15
```

Attendu : 4 passed

- [ ] **Step 3 : Commit**

```bash
cd /opt/stacks/wally-ai
git add tests/test_twitch_commands_mood.py
git commit -m "test(twitch): add unit tests for handle_mood_command"
```

---

### Task 2 : Tests pour `handle_code_command`

**Files:**
- Create: `tests/test_twitch_commands_code.py`

- [ ] **Step 1 : Écrire les tests**

```python
# tests/test_twitch_commands_code.py
import json
import pytest
from datetime import date
from unittest.mock import MagicMock, AsyncMock, patch


def make_bot(note_value=None):
    bot = MagicMock()
    bot.db.get_persistent_note = AsyncMock(return_value=note_value)
    bot.db.upsert_persistent_note = AsyncMock()
    bot._channel_ids = {}
    bot.twitch_api.send_message = AsyncMock()
    irc_channel = MagicMock()
    irc_channel.send = AsyncMock()
    bot.get_channel.return_value = irc_channel
    return bot


def make_mod_badge():
    b = MagicMock()
    b.id = "moderator"
    return b


def make_broadcaster_badge():
    b = MagicMock()
    b.id = "broadcaster"
    return b


def make_viewer_badge():
    b = MagicMock()
    b.id = "subscriber"
    return b


@pytest.fixture(autouse=True)
def clear_state():
    """Vide _daily_codes entre les tests pour éviter les fuites d'état."""
    from bot.twitch.commands import code as code_mod
    code_mod._daily_codes.clear()
    yield
    code_mod._daily_codes.clear()


@pytest.mark.asyncio
async def test_code_no_code_set_shows_no_code_message():
    """!code sans code défini → message 'Pas de code'."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Pas de code" in text


@pytest.mark.asyncio
async def test_code_displays_code_with_reminder():
    """!code avec code défini → affiche le code + le RAPPEL."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "ABC123", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "ABC123" in text
    assert "ON DIT BONJOUR" in text
    assert "RAPPEL" in text


@pytest.mark.asyncio
async def test_code_set_by_moderator_saves_and_displays():
    """!code ABC par un modérateur → sauvegarde en DB + affiche le code."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    badges = [make_mod_badge()]
    await handle_code_command(bot, "streamer", "mod1", "NEWCODE", badges)
    # DB sauvegardée
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved_json = bot.db.upsert_persistent_note.call_args.args[1]
    assert "NEWCODE" in saved_json
    # Message affiché
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "NEWCODE" in text
    assert "ON DIT BONJOUR" in text


@pytest.mark.asyncio
async def test_code_set_by_broadcaster_saves():
    """!code par broadcaster → accepté."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "owner", "MYCODE", [make_broadcaster_badge()])
    bot.db.upsert_persistent_note.assert_awaited_once()


@pytest.mark.asyncio
async def test_code_set_rejected_for_viewer():
    """!code par un viewer → refusé, DB non touchée."""
    from bot.twitch.commands.code import handle_code_command
    bot = make_bot(note_value=None)
    await handle_code_command(bot, "streamer", "viewer", "HACK", [make_viewer_badge()])
    bot.db.upsert_persistent_note.assert_not_awaited()
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "modérateurs" in text.lower() or "Seuls" in text


@pytest.mark.asyncio
async def test_code_resets_if_date_changed():
    """Si le code sauvegardé vient d'hier, il est reset à None."""
    from bot.twitch.commands.code import handle_code_command
    yesterday_note = json.dumps({"code": "OLDCODE", "date": "2000-01-01"})
    bot = make_bot(note_value=yesterday_note)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "Pas de code" in text
    # DB mise à jour avec date d'aujourd'hui et code None
    bot.db.upsert_persistent_note.assert_awaited_once()
    saved = json.loads(bot.db.upsert_persistent_note.call_args.args[1])
    assert saved["code"] is None
    assert saved["date"] == str(date.today())


@pytest.mark.asyncio
async def test_code_loaded_from_db_on_first_access():
    """Au premier accès, le code est chargé depuis la DB."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "DBCODE", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "newchannel", "viewer1", "", [])
    bot.db.get_persistent_note.assert_awaited_once_with("twitch_code:newchannel")
    text = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "DBCODE" in text


@pytest.mark.asyncio
async def test_code_not_reloaded_from_db_on_second_call():
    """Au deuxième appel, la DB n'est plus consultée (cache mémoire)."""
    from bot.twitch.commands.code import handle_code_command
    today = str(date.today())
    saved = json.dumps({"code": "CACHED", "date": today})
    bot = make_bot(note_value=saved)
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    await handle_code_command(bot, "streamer", "viewer1", "", [])
    assert bot.db.get_persistent_note.await_count == 1  # chargé une seule fois
```

- [ ] **Step 2 : Vérifier que les tests passent**

```bash
cd /opt/stacks/wally-ai && python3 -m pytest tests/test_twitch_commands_code.py -v 2>&1 | tail -20
```

Attendu : 8 passed

- [ ] **Step 3 : Commit**

```bash
cd /opt/stacks/wally-ai
git add tests/test_twitch_commands_code.py
git commit -m "test(twitch): add unit tests for handle_code_command"
```
