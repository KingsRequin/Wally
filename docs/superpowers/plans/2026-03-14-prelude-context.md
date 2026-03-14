# Prelude Context Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à Wally un historique des N derniers messages précédant sa mention dans un canal Discord/Twitch, via un buffer passif + fallback `channel.history()`.

**Architecture:** Buffer circulaire `_prelude_windows` dans `MemoryService`, capturant passivement tous les messages non-bot dans les canaux autorisés. Au moment d'une mention, le prelude est passé à `_respond()` et injecté dans le prompt avant le contexte existant. En cas de démarrage à froid (buffer vide), fallback `channel.history()` pour Discord uniquement.

**Tech Stack:** Python asyncio, discord.py 2.x, twitchio 2.x, pytest + pytest-asyncio, MagicMock/AsyncMock

**Spec:** `docs/superpowers/specs/2026-03-14-prelude-context-design.md`

---

## Chunk 1: Config + MemoryService

### Task 1: Ajouter `prelude_window_size` à la config

**Files:**
- Modify: `bot/config.py`
- Modify: `config.yaml`
- Modify: `tests/test_config.py` (MINIMAL_CONFIG)

- [ ] **Step 1 : Vérifier que les tests config passent actuellement**

```bash
cd /opt/stacks/wally-ai && pytest tests/test_config.py -v
```
Expected: tous PASS.

- [ ] **Step 2 : Ajouter le champ dans `BotConfig`**

Dans `bot/config.py`, ajouter `prelude_window_size` avec une valeur par défaut pour ne pas casser les tests existants :

```python
@dataclass
class BotConfig:
    trigger_names: list[str]
    language_default: str
    context_window_size: int
    context_token_threshold: int
    journal_time: str
    system_prompt: str
    journal_channel_id: Optional[int] = None
    dashboard_token: Optional[str] = None
    prelude_window_size: int = 15
```

- [ ] **Step 3 : Ajouter la clé dans `config.yaml`**

Ajouter `prelude_window_size: 15` dans la section `bot:` du fichier `config.yaml`.

- [ ] **Step 4 : Mettre à jour `MINIMAL_CONFIG` dans les tests**

Dans `tests/test_config.py`, ajouter la clé dans `MINIMAL_CONFIG["bot"]` :

```python
"bot": {
    "trigger_names": ["wally"],
    "language_default": "fr",
    "context_window_size": 20,
    "context_token_threshold": 3000,
    "journal_time": "03:00",
    "journal_channel_id": None,
    "dashboard_token": None,
    "system_prompt": "Tu es Wally.",
    "prelude_window_size": 15,   # ← nouveau
},
```

- [ ] **Step 5 : Ajouter une assertion dans `test_load_config`**

Dans `tests/test_config.py`, ajouter dans le corps de `test_load_config` :

```python
assert config.bot.prelude_window_size == 15
```

- [ ] **Step 6 : Vérifier que les tests config passent toujours**

```bash
pytest tests/test_config.py -v
```
Expected: tous PASS.

- [ ] **Step 7 : Commit**

```bash
git add bot/config.py config.yaml tests/test_config.py
git commit -m "feat: add prelude_window_size to BotConfig (default 15)"
```

---

### Task 2: Prelude buffer dans `MemoryService`

**Files:**
- Modify: `bot/core/memory.py`
- Modify: `tests/test_memory.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_memory.py` :

```python
# ── Prelude buffer ────────────────────────────────────────────────────────────

def make_config_prelude(window_size=5, token_threshold=100, prelude_size=3):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = prelude_size
    return config


def test_append_prelude_circular():
    svc = MemoryService(make_config_prelude(prelude_size=3))
    for i in range(5):
        svc.append_prelude("ch1", "User", f"msg {i}")
    result = svc.get_prelude("ch1")
    assert len(result) == 3
    assert result[0]["content"] == "msg 2"  # oldest kept


def test_get_prelude_returns_copy():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    copy = svc.get_prelude("ch1")
    copy.append({"author": "X", "content": "injected", "timestamp": 0})
    assert len(svc.get_prelude("ch1")) == 1  # original untouched


def test_prelude_independent_from_context_windows():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "prelude msg")
    svc.append_message("ch1", "Alice", "context msg")
    assert len(svc.get_prelude("ch1")) == 1
    assert len(svc.get_context("ch1")) == 1
    assert svc.get_prelude("ch1")[0]["content"] == "prelude msg"
    assert svc.get_context("ch1")[0]["content"] == "context msg"


def test_prelude_reset_clears_buffer():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    assert len(svc.get_prelude("ch1")) == 1
    # reset_all() doit aussi purger _prelude_windows
    import asyncio
    asyncio.run(svc.reset_all())
    assert svc.get_prelude("ch1") == []
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_memory.py::test_append_prelude_circular \
       tests/test_memory.py::test_get_prelude_returns_copy \
       tests/test_memory.py::test_prelude_independent_from_context_windows \
       tests/test_memory.py::test_prelude_reset_clears_buffer -v
```
Expected: 4 × FAILED (AttributeError: 'MemoryService' object has no attribute 'append_prelude').

- [ ] **Step 3 : Implémenter dans `MemoryService`**

Dans `bot/core/memory.py`, modifier `__init__` et ajouter les méthodes :

```python
def __init__(self, config: "Config"):
    self._config = config
    self._mem0: Optional[object] = None
    self._mem0_init_attempted: bool = False
    self._context_windows: dict[str, list[dict]] = {}
    self._prelude_windows: dict[str, list[dict]] = {}   # ← nouveau
    self._openai: Optional["OpenAIClient"] = None
```

Mettre à jour `reset_all()` — ajouter `self._prelude_windows.clear()` :

```python
async def reset_all(self) -> None:
    """Clear all context windows and all mem0 long-term memories."""
    self._context_windows.clear()
    self._prelude_windows.clear()   # ← nouveau
    logger.info("Memory context windows cleared")
    if self._mem0 is not None:
        try:
            await asyncio.to_thread(self._mem0.reset)
            logger.info("mem0 long-term memory reset")
        except Exception as exc:
            logger.warning("mem0 reset failed: {e}", e=exc)
```

Ajouter les deux nouvelles méthodes après `get_context()` :

```python
def append_prelude(self, channel_id: str, author: str, content: str) -> None:
    window = self._prelude_windows.setdefault(channel_id, [])
    window.append(
        {"author": author, "content": content, "timestamp": time.time()}
    )
    max_size = self._config.bot.prelude_window_size
    if len(window) > max_size:
        self._prelude_windows[channel_id] = window[-max_size:]

def get_prelude(self, channel_id: str) -> list[dict]:
    return list(self._prelude_windows.get(channel_id, []))
```

- [ ] **Step 4 : Vérifier que les 4 tests passent**

```bash
pytest tests/test_memory.py -v
```
Expected: tous PASS (nouveaux + existants).

- [ ] **Step 5 : Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat: add prelude buffer to MemoryService (append_prelude, get_prelude)"
```

---

## Chunk 2: Prompts + Discord handlers

### Task 3: `build_prelude_block()` dans `PromptBuilder`

**Files:**
- Modify: `bot/core/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_prompts.py` :

```python
# ── build_prelude_block ───────────────────────────────────────────────────────

def test_build_prelude_block_empty():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    assert pb.build_prelude_block([]) == ""


def test_build_prelude_block_formats_messages():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    messages = [
        {"author": "Alice", "content": "Salut tout le monde", "timestamp": 1.0},
        {"author": "Bob", "content": "Ça roule ?", "timestamp": 2.0},
    ]
    result = pb.build_prelude_block(messages)
    assert "[Alice]: Salut tout le monde" in result
    assert "[Bob]: Ça roule ?" in result
    assert result != ""
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
pytest tests/test_prompts.py::test_build_prelude_block_empty \
       tests/test_prompts.py::test_build_prelude_block_formats_messages -v
```
Expected: 2 × FAILED (AttributeError: 'PromptBuilder' object has no attribute 'build_prelude_block').

- [ ] **Step 3 : Implémenter dans `prompts.py`**

Ajouter la constante après `CONTEXT_HEADER` :

```python
PRELUDE_HEADER = (
    "\n--- Discussion récente dans le canal (avant ta mention) ---\n"
    "{context}\n"
    "--- Fin de la discussion ---"
)
```

Ajouter la méthode dans `PromptBuilder`, après `build_context_block()` :

```python
def build_prelude_block(self, messages: list[dict]) -> str:
    if not messages:
        return ""
    lines = [f"[{m['author']}]: {m['content']}" for m in messages]
    return PRELUDE_HEADER.format(context="\n".join(lines))
```

- [ ] **Step 4 : Vérifier que tous les tests prompts passent**

```bash
pytest tests/test_prompts.py -v
```
Expected: tous PASS.

- [ ] **Step 5 : Commit**

```bash
git add bot/core/prompts.py tests/test_prompts.py
git commit -m "feat: add build_prelude_block to PromptBuilder"
```

---

### Task 4: Discord handlers — capture passive + fallback + intégration

**Files:**
- Modify: `bot/discord/handlers.py`
- Modify: `tests/test_discord_handlers.py`

- [ ] **Step 1 : Mettre à jour `make_bot()` et les appels directs à `_respond` dans les tests**

Dans `tests/test_discord_handlers.py`, ajouter les mocks manquants dans `make_bot()` :

```python
def make_bot(trigger_names=None, muted=False, welcomed=False, trust=0.5):
    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = trigger_names or ["wally"]
    bot.config.bot.prelude_window_size = 5        # ← nouveau
    bot.config.discord.allowed_channels = []
    bot.config.discord.anger_trigger_threshold = 3
    bot.config.discord.timeout_minutes = 10

    bot.db.is_muted = AsyncMock(return_value=muted)
    bot.db.is_welcomed = AsyncMock(return_value=welcomed)
    bot.db.get_trust_score = AsyncMock(return_value=trust)
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()

    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.emotion.process_message = AsyncMock()

    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_prelude = MagicMock(return_value=[])      # ← nouveau
    bot.memory.append_prelude = MagicMock()                  # ← nouveau

    bot.language.detect = MagicMock(return_value="fr")
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")  # ← nouveau
    bot.openai.complete = AsyncMock(return_value="Bonjour!")

    return bot


# ⚠️ IMPORTANT : `_respond` change de signature (ajout de `prelude: list[dict]`).
# Mettre à jour les 3 appels directs existants dans ce fichier :
#   ligne ~121 : await _respond(bot, message, "12345", "99999")
#   ligne ~131 : await _respond(bot, message, "12345", "99999")
#   ligne ~144 : await _respond(bot, message, "12345", "99999")
# → remplacer par : await _respond(bot, message, "12345", "99999", [])
#
# Faire ce remplacement avant d'écrire les nouveaux tests et avant d'implémenter.
```

- [ ] **Step 2 : Écrire les nouveaux tests qui échouent**

Ajouter à la fin de `tests/test_discord_handlers.py` :

```python
# ── Prelude context ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passive_capture_non_triggered_message():
    """append_prelude est appelé même sans trigger, dans les canaux autorisés."""
    bot = make_bot()
    message = make_message(content="juste un message normal")  # pas de trigger
    # bot.user pas dans les mentions, pas de trigger name dans content
    await handle_message(bot, message)
    bot.memory.append_prelude.assert_called_once_with(
        str(message.channel.id),
        message.author.display_name,
        message.content,
    )
    # pas de réponse envoyée
    bot.openai.complete.assert_not_called()


@pytest.mark.asyncio
async def test_prelude_included_in_prompt_on_mention():
    """build_prelude_block est appelé avec le prelude au moment de la mention."""
    bot = make_bot()
    prelude_msgs = [{"author": "Alice", "content": "on parlait de trucs", "timestamp": 1.0}]
    bot.memory.get_prelude = MagicMock(return_value=prelude_msgs)
    bot.prompts.build_prelude_block = MagicMock(return_value="[PRELUDE]")

    message = make_message(content="wally c'est quoi ton avis")
    await handle_message(bot, message)

    bot.prompts.build_prelude_block.assert_called_once_with(prelude_msgs)
    # Le prelude doit apparaître dans user_content envoyé à OpenAI
    call_args = bot.openai.complete.call_args
    user_content = call_args[0][1][0]["content"]  # messages[0]["content"]
    assert "[PRELUDE]" in user_content


@pytest.mark.asyncio
async def test_cold_start_fallback_to_channel_history():
    """Si prelude vide, channel.history() est appelé en fallback."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide = cold start

    # Mock channel.history() — retourne 2 messages dans l'ordre inverse (Discord API)
    history_msg1 = MagicMock()
    history_msg1.author.bot = False
    history_msg1.author.display_name = "Alice"
    history_msg1.content = "premier message"

    history_msg2 = MagicMock()
    history_msg2.author.bot = False
    history_msg2.author.display_name = "Bob"
    history_msg2.content = "deuxième message"

    async def fake_history(limit):
        for m in [history_msg2, history_msg1]:  # Discord retourne du plus récent au plus ancien
            yield m

    message = make_message(content="wally dis moi")
    message.channel.history = fake_history

    await handle_message(bot, message)

    # build_prelude_block doit avoir reçu les messages dans l'ordre chronologique
    call_args = bot.prompts.build_prelude_block.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0]["author"] == "Alice"   # ordre chronologique : plus ancien d'abord
    assert call_args[1]["author"] == "Bob"


@pytest.mark.asyncio
async def test_channel_history_permission_error_graceful():
    """Une erreur sur channel.history() → log WARNING + réponse sans prelude."""
    bot = make_bot()
    bot.memory.get_prelude = MagicMock(return_value=[])  # vide

    async def broken_history(limit):
        raise Exception("Missing Access")
        return  # pragma: no cover
        yield  # make it a generator

    message = make_message(content="wally aide moi")
    message.channel.history = broken_history

    # Ne doit pas lever d'exception
    await handle_message(bot, message)

    # build_prelude_block appelé avec liste vide (graceful degradation)
    bot.prompts.build_prelude_block.assert_called_once_with([])
    # La réponse est quand même envoyée
    bot.openai.complete.assert_called_once()
```

- [ ] **Step 3 : Vérifier que les 4 nouveaux tests échouent**

```bash
pytest tests/test_discord_handlers.py::test_passive_capture_non_triggered_message \
       tests/test_discord_handlers.py::test_prelude_included_in_prompt_on_mention \
       tests/test_discord_handlers.py::test_cold_start_fallback_to_channel_history \
       tests/test_discord_handlers.py::test_channel_history_permission_error_graceful -v
```
Expected: 4 × FAILED.

- [ ] **Step 4 : Implémenter dans `bot/discord/handlers.py`**

Remplacer `handle_message` et `_respond` selon le design. Le code complet de `handle_message` devient :

```python
async def handle_message(bot: "WallyDiscord", message: discord.Message) -> None:
    if message.author.bot:
        return

    # Capture passive + récupération prelude AVANT d'ajouter le message courant
    allowed = bot.config.discord.allowed_channels
    if not allowed or message.channel.id in allowed:
        prelude = bot.memory.get_prelude(str(message.channel.id))
        bot.memory.append_prelude(
            str(message.channel.id), message.author.display_name, message.content
        )
    else:
        prelude = []

    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    triggered = mentioned or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    if allowed and message.channel.id not in allowed:
        return

    user_id = str(message.author.id)
    guild_id = str(message.guild.id) if message.guild else "dm"

    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        return

    await _respond(bot, message, user_id, guild_id, prelude)
    _fire(_maybe_welcome(bot, message, user_id, guild_id))
```

Ajouter la fonction `_fetch_discord_history` après `_fire` :

```python
async def _fetch_discord_history(channel, limit: int) -> list[dict]:
    """Fallback cold start : récupère l'historique Discord via API.
    Retourne les messages en ordre chronologique (plus ancien en premier).
    Retourne [] en cas d'erreur (permissions, etc.).
    Note : dicts sans 'timestamp' — utilisés uniquement pour le prompt,
    non stockés dans _prelude_windows."""
    try:
        msgs = []
        async for m in channel.history(limit=limit):
            if not m.author.bot:
                msgs.append({"author": m.author.display_name, "content": m.content})
        msgs.reverse()  # Discord renvoie du plus récent au plus ancien
        return msgs
    except Exception as e:
        logger.warning("channel.history() fallback failed: {e}", e=e)
        return []
```

Modifier la signature de `_respond` pour accepter `prelude` :

```python
async def _respond(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
    prelude: list[dict],
) -> None:
    try:
        await message.add_reaction("🔍")

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, message.content)
        context_messages = await bot.memory.get_context_summarized_if_needed(
            str(message.channel.id)
        )

        # Fallback cold start si prelude vide
        if not prelude:
            prelude = await _fetch_discord_history(
                message.channel, bot.config.bot.prelude_window_size
            )

        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_messages)

        user_content = (
            prelude_block
            + context_block
            + f"\n[{message.author.display_name}]: {message.content}"
        )

        openai_messages = [{"role": "user", "content": user_content}]

        async with message.channel.typing():
            reply = await bot.openai.complete(
                system_prompt, openai_messages, purpose="discord_response"
            )

        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        await _send_in_parts(message, reply)

        bot.memory.append_message(
            str(message.channel.id), message.author.display_name, message.content
        )
        bot.memory.append_message(str(message.channel.id), "Wally", reply)

        _fire(_post_process(bot, message.content, platform, user_id, guild_id, trust))

    except Exception as e:
        logger.error("Error handling Discord message: {e}", e=e)
        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
```

- [ ] **Step 5 : Vérifier que tous les tests Discord passent**

```bash
pytest tests/test_discord_handlers.py -v
```
Expected: tous PASS (nouveaux + existants).

- [ ] **Step 6 : Commit**

```bash
git add bot/discord/handlers.py tests/test_discord_handlers.py
git commit -m "feat: add passive prelude capture and cold-start fallback to Discord handlers"
```

---

## Chunk 3: Twitch handlers + vérification finale

### Task 5: Twitch handlers — capture passive

**Files:**
- Modify: `bot/twitch/handlers.py`

Note : Twitch n'a pas d'API `history()`. Pas de fallback, pas de nouveaux tests unitaires
(la logique `append_prelude` / `get_prelude` est déjà testée dans `test_memory.py`).

- [ ] **Step 1 : Modifier `handle_message` dans `bot/twitch/handlers.py`**

```python
async def handle_message(bot: "WallyTwitch", payload) -> None:
    """Handle an incoming channel.chat.message EventSub payload."""
    content: str = payload.message.text
    content_lower = content.lower()
    author: str = payload.chatter.name
    user_id: str = str(payload.chatter.id)
    channel_name: str = payload.broadcaster.name
    channel_id = f"twitch:{channel_name}"

    # Capture passive : prelude AVANT d'ajouter le message courant
    prelude = bot.memory.get_prelude(channel_id)
    bot.memory.append_prelude(channel_id, author, content)

    # Trigger check
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

        mem_context = await bot.memory.search(platform, user_id, content)
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
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)
        user_content = prelude_block + context_block + f"\n[{author}]: {content}"

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
```

Note : `channel_name` est extrait **avant** le trigger check pour `channel_id` du prelude. Ces deux lignes sont intentionnellement sorties du bloc `try` existant — si `payload.broadcaster` est absent, l'exception remonte sans être catchée, ce qui est acceptable (payload malformé = bug en amont).

- [ ] **Step 2 : Lancer la suite de tests complète**

```bash
pytest -v
```
Expected: tous PASS. Compter que le total est >= 110 + 9 nouveaux = 119 tests.

- [ ] **Step 3 : Commit final**

```bash
git add bot/twitch/handlers.py
git commit -m "feat: add passive prelude capture to Twitch handler"
```
