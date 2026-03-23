# Spontaneous Memory Recall — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wally évoque spontanément des souvenirs anciens quand le contexte s'y prête — à la fois dans les interventions spontanées et dans les réponses normales.

**Architecture:** Nouvelle méthode `search_top_match()` dans MemoryService pour obtenir le meilleur souvenir avec score. Check mémoire async ajouté après `_check_spontaneous_trigger()` dans les handlers Discord/Twitch. Directive LLM dans un nouveau prompt .md injectée dans `build_system_prompt()`.

**Tech Stack:** Python asyncio, mem0/Qdrant, PromptBuilder, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-spontaneous-memory-recall-design.md`

---

### Task 1: Config — Nouveaux champs BotConfig

**Files:**
- Modify: `bot/config.py:28` (après `spontaneous_cooldown_seconds`)
- Test: `tests/test_spontaneous.py`

- [ ] **Step 1: Add config fields**

In `bot/config.py`, add after line 28 (`spontaneous_cooldown_seconds: int = 300`):

```python
    spontaneous_memory_probability: float = 0.2
    memory_recall_min_score: float = 0.75
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/ -x -q`
Expected: All tests pass (no breakage from new default fields)

- [ ] **Step 3: Commit**

```bash
git add bot/config.py
git commit -m "feat(config): add spontaneous memory recall settings"
```

---

### Task 2: MemoryService.search_top_match()

**Files:**
- Modify: `bot/core/memory.py:494` (after `search()` method)
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_memory.py`:

```python
@pytest.mark.asyncio
async def test_search_top_match_returns_best():
    """search_top_match returns the highest-scoring memory with its score."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"memory": "aime le Python", "score": 0.6},
            {"memory": "joue à Apex", "score": 0.85},
            {"memory": "habite à Lyon", "score": 0.4},
        ]
    }
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "quel jeu tu fais")
    assert result is not None
    text, score = result
    assert text == "joue à Apex"
    assert score == 0.85


@pytest.mark.asyncio
async def test_search_top_match_no_results():
    """search_top_match returns None when no results above threshold."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {"results": []}
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "random query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_below_min_score():
    """search_top_match returns None when all results are below _MIN_SEARCH_SCORE."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"memory": "some fact", "score": 0.1},
            {"memory": "another fact", "score": 0.2},
        ]
    }
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_qdrant_error():
    """search_top_match returns None and logs warning on Qdrant failure."""
    svc = MemoryService(make_config())
    mock_mem0 = MagicMock()
    mock_mem0.search.side_effect = Exception("Qdrant unavailable")
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_empty_query():
    """search_top_match returns None for empty/whitespace queries."""
    svc = MemoryService(make_config())
    svc._mem0 = MagicMock()
    result = await svc.search_top_match("discord", "12345", "")
    assert result is None
    result2 = await svc.search_top_match("discord", "12345", "   ")
    assert result2 is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory.py::test_search_top_match_returns_best -v`
Expected: FAIL with `AttributeError: 'MemoryService' object has no attribute 'search_top_match'`

- [ ] **Step 3: Implement search_top_match()**

Add after the `search()` method in `bot/core/memory.py` (after line 494):

```python
    async def search_top_match(
        self, platform: str, user_id: str, query: str,
    ) -> tuple[str, float] | None:
        """Return the single best memory match with its score, or None.

        Unlike search(), this does a single Qdrant query (no dual-query)
        and returns the raw score for threshold comparison.
        """
        self._init_mem0()
        if self._mem0 is None:
            return None
        if not query or not query.strip():
            return None
        try:
            uid = self._user_id(platform, user_id)
            results = await asyncio.to_thread(
                self._mem0.search, query, user_id=uid, limit=3
            )
            if isinstance(results, dict):
                results = results.get("results", [])

            best: tuple[str, float] | None = None
            for r in results or []:
                mem = r.get("memory", "")
                score = r.get("score", 0.0)
                if mem and score >= _MIN_SEARCH_SCORE:
                    if best is None or score > best[1]:
                        best = (mem, score)
            return best
        except Exception as exc:
            logger.warning("mem0 search_top_match failed: {e}", e=exc)
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory.py -k "search_top_match" -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add bot/core/memory.py tests/test_memory.py
git commit -m "feat(memory): add search_top_match() for spontaneous recall"
```

---

### Task 3: Directive prompt pour les réponses normales

**Files:**
- Create: `bot/persona/prompts/memory_recall_directive.md`
- Modify: `bot/core/prompts.py:152-156` (injection after memory block)
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prompts.py`:

```python
def test_memory_recall_directive_injected():
    """When memory_context is present, the recall directive is injected."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        memory_context="Aime le Python et joue à Apex.",
    )
    assert "Ce que tu sais de cet utilisateur" in result
    assert "souvenir" in result.lower() or "rappelle" in result.lower()


def test_memory_recall_directive_absent_when_no_memory():
    """When memory_context is empty, no recall directive is injected."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
    )
    # Should not contain any memory recall directive
    assert "ça me rappelle" not in result.lower()
    assert "souvenir" not in result.lower()
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `pytest tests/test_prompts.py::test_memory_recall_directive_injected -v`
Expected: FAIL (no directive content in output yet)

- [ ] **Step 3: Create the directive prompt file**

Create `bot/persona/prompts/memory_recall_directive.md`:

```markdown
Si les souvenirs ci-dessus contiennent quelque chose en lien avec la conversation actuelle, tu peux l'évoquer naturellement. Utilise des formulations comme "ça me rappelle quand tu parlais de...", "d'ailleurs tu m'avais dit que...", "tiens, la dernière fois tu...".

Ne le fais pas systématiquement — seulement quand c'est pertinent et que ça enrichit l'échange. Ne récite jamais un souvenir mot à mot, reformule-le naturellement. Ne révèle jamais d'informations qu'un utilisateur a partagées en privé. N'invente jamais de faux souvenirs — base-toi uniquement sur ce qui est écrit ci-dessus.
```

- [ ] **Step 4: Inject directive in build_system_prompt()**

In `bot/core/prompts.py`, add at module level (after `load_prompt` definition, around line 30):

```python
_MEMORY_RECALL_DIRECTIVE = load_prompt("memory_recall_directive")
```

Then modify the memory context injection block (lines 152-156). Replace:

```python
        # Long-term memory context
        if memory_context:
            parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
            )
```

With:

```python
        # Long-term memory context
        if memory_context:
            parts.append(
                f"\n--- Ce que tu sais de cet utilisateur ---\n{memory_context}"
            )
            if _MEMORY_RECALL_DIRECTIVE:
                parts.append(_MEMORY_RECALL_DIRECTIVE)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_prompts.py -v`
Expected: All tests PASS (including the 2 new ones)

- [ ] **Step 6: Commit**

```bash
git add bot/persona/prompts/memory_recall_directive.md bot/core/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): add memory recall directive for normal responses"
```

---

### Task 4: Discord handler — trigger mémoire spontané

**Files:**
- Modify: `bot/discord/handlers.py:279-302` (spontaneous block in `handle_message`)
- Modify: `bot/discord/handlers.py:731-784` (`_spontaneous_respond`)
- Test: `tests/test_spontaneous.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_spontaneous.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time
from bot.discord.handlers import _check_spontaneous_trigger


def _make_msg(content="je vais lancer une partie"):
    """Helper to build a minimal discord.Message-like mock."""
    msg = MagicMock()
    msg.content = content
    msg.author.id = 12345
    msg.author.bot = False
    msg.author.display_name = "TestUser"
    msg.guild = MagicMock()
    msg.guild.id = 99999
    msg.guild.name = "TestServer"
    msg.channel = MagicMock()
    msg.channel.id = 777
    msg.channel.name = "general"
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.reply = AsyncMock()
    msg.add_reaction = AsyncMock()
    return msg


def make_bot_for_spontaneous():
    bot = MagicMock()
    bot.config.bot.spontaneous_memory_probability = 0.2
    bot.config.bot.memory_recall_min_score = 0.75
    bot.config.bot.spontaneous_cooldown_seconds = 300
    bot.config.bot.spontaneous_discord_enabled = True
    bot.config.bot.spontaneous_probability = 0.05
    bot.config.bot.spontaneous_passion_probability = 0.15
    bot.config.discord.allowed_channels = []
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.spam_detection.enabled = False
    bot.user = MagicMock()
    bot.memory.search_top_match = AsyncMock(return_value=None)
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.append_message = MagicMock()
    bot.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
    )
    bot.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.openai.complete = AsyncMock(return_value="Ah oui, ça me rappelle!")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="persona")
    return bot


@pytest.mark.asyncio
async def test_spontaneous_memory_trigger_fires():
    """Full handler flow: memory recall triggers _fire when score >= threshold."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")  # no passion keyword

    handlers._spontaneous_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1  # < 0.2 probability
        await handle_message(bot, msg)

        # _fire should have been called with _spontaneous_respond + recall_memory
        assert mock_fire.called
        fired_coro = mock_fire.call_args.args[0]
        # The coroutine name should be _spontaneous_respond
        assert "spontaneous_respond" in fired_coro.__name__


@pytest.mark.asyncio
async def test_spontaneous_memory_below_threshold():
    """No _fire when memory score is below memory_recall_min_score."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("some memory", 0.5))
    msg = _make_msg("je vais au magasin")  # no passion keyword, no emotion

    handlers._spontaneous_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1
        await handle_message(bot, msg)
        assert not mock_fire.called


@pytest.mark.asyncio
async def test_spontaneous_memory_probability_blocks():
    """No _fire when random exceeds spontaneous_memory_probability."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")

    handlers._spontaneous_cooldowns.clear()
    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.9  # > 0.2 probability → blocked
        await handle_message(bot, msg)
        assert not mock_fire.called


@pytest.mark.asyncio
async def test_spontaneous_memory_cooldown():
    """Memory recall respects the spontaneous cooldown — no trigger if cooldown active."""
    from bot.discord import handlers
    from bot.discord.handlers import handle_message

    bot = make_bot_for_spontaneous()
    bot.memory.search_top_match = AsyncMock(return_value=("joue à Apex", 0.85))
    msg = _make_msg("je vais lancer une partie")

    # Set cooldown as recently fired
    import time as _time
    handlers._spontaneous_cooldowns["777"] = _time.time()

    with patch("bot.discord.handlers.random") as mock_random, \
         patch("bot.discord.handlers._fire") as mock_fire:
        mock_random.random.return_value = 0.1
        await handle_message(bot, msg)
        # Cooldown not elapsed → no trigger, no Qdrant query
        assert not mock_fire.called
        bot.memory.search_top_match.assert_not_called()


@pytest.mark.asyncio
async def test_spontaneous_respond_with_memory_injects_recall():
    """_spontaneous_respond injects memory recall into user_content."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    msg = _make_msg("je vais lancer une partie")

    await _spontaneous_respond(bot, msg, recall_memory="joue à Apex")

    # Check the user_content contains the recall block
    complete_call = bot.openai.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" in user_content
    # Check memory_context was passed to build_system_prompt
    prompt_kwargs = bot.prompts.build_system_prompt.call_args.kwargs
    assert prompt_kwargs.get("memory_context") == "joue à Apex"


@pytest.mark.asyncio
async def test_spontaneous_respond_without_memory():
    """_spontaneous_respond works normally without recall_memory (regression)."""
    from bot.discord.handlers import _spontaneous_respond
    bot = make_bot_for_spontaneous()
    msg = _make_msg("bouchon")

    await _spontaneous_respond(bot, msg)  # no recall_memory

    complete_call = bot.openai.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" not in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spontaneous.py -v`
Expected: New tests FAIL (signature mismatch, missing features)

- [ ] **Step 3: Modify _spontaneous_respond() to accept recall_memory**

In `bot/discord/handlers.py`, modify `_spontaneous_respond` (line 731):

Replace the signature:
```python
async def _spontaneous_respond(bot: "WallyDiscord", message: discord.Message) -> None:
```
With:
```python
async def _spontaneous_respond(
    bot: "WallyDiscord", message: discord.Message,
    recall_memory: str | None = None,
) -> None:
```

Replace the system_prompt build (lines 741-748):
```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```
With:
```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```

Replace the user_content build (lines 750-755):
```python
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + prelude_block
            + f"\n[{message.author.display_name}]: {message.content}"
        )
```
With:
```python
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{message.author.display_name}. Évoque-le naturellement.\n\n"
            )
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + recall_block
            + prelude_block
            + f"\n[{message.author.display_name}]: {message.content}"
        )
```

Add logging after the existing `logger.info` (line 780):
```python
        if recall_memory:
            logger.info("Memory recall for {user}: {mem}", user=message.author.display_name, mem=recall_memory[:80])
```

- [ ] **Step 4: Add memory check in the spontaneous block of handle_message**

In `bot/discord/handlers.py`, modify the spontaneous block (lines 279-302).

Replace:
```python
        # Spontaneous intervention
        if channel_allowed and bot.config.bot.spontaneous_discord_enabled:
            import time as _time
            state = bot.emotion.get_state()
            trigger_type = _check_spontaneous_trigger(
                message.content,
                curiosity=state.get("curiosity", 0.0),
                anger=state.get("anger", 0.0),
                boredom=state.get("boredom", 0.0),
            )
            if trigger_type:
                chan_id = str(message.channel.id)
                now = _time.time()
                cooldown = bot.config.bot.spontaneous_cooldown_seconds
                if now - _spontaneous_cooldowns.get(chan_id, 0) >= cooldown:
                    prob = (
                        bot.config.bot.spontaneous_passion_probability
                        if trigger_type == "passion"
                        else bot.config.bot.spontaneous_probability
                    )
                    if random.random() < prob:
                        _spontaneous_cooldowns[chan_id] = now
                        _fire(_spontaneous_respond(bot, message))
            return
```

With:
Also add a module-level dict for memory check rate-limiting (near the existing `_spontaneous_cooldowns`):

```python
_memory_check_cooldowns: dict[str, float] = {}  # rate-limit Qdrant checks per channel
```

Then the replacement block:

```python
        # Spontaneous intervention
        if channel_allowed and bot.config.bot.spontaneous_discord_enabled:
            import time as _time
            state = bot.emotion.get_state()
            trigger_type = _check_spontaneous_trigger(
                message.content,
                curiosity=state.get("curiosity", 0.0),
                anger=state.get("anger", 0.0),
                boredom=state.get("boredom", 0.0),
            )
            chan_id = str(message.channel.id)
            now = _time.time()
            cooldown = bot.config.bot.spontaneous_cooldown_seconds
            cooldown_ok = now - _spontaneous_cooldowns.get(chan_id, 0) >= cooldown

            if trigger_type and cooldown_ok:
                prob = (
                    bot.config.bot.spontaneous_passion_probability
                    if trigger_type == "passion"
                    else bot.config.bot.spontaneous_probability
                )
                if random.random() < prob:
                    _spontaneous_cooldowns[chan_id] = now
                    _fire(_spontaneous_respond(bot, message))
            elif not trigger_type and cooldown_ok:
                # Memory recall check — rate-limited to 1 per 60s per channel
                if now - _memory_check_cooldowns.get(chan_id, 0) >= 60:
                    _memory_check_cooldowns[chan_id] = now
                    match = await bot.memory.search_top_match(
                        "discord", str(message.author.id), message.content,
                    )
                    if match and match[1] >= bot.config.bot.memory_recall_min_score:
                        if random.random() < bot.config.bot.spontaneous_memory_probability:
                            _spontaneous_cooldowns[chan_id] = now
                            _fire(_spontaneous_respond(bot, message, recall_memory=match[0]))
            return
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_spontaneous.py -v`
Expected: All tests PASS (old + new)

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add bot/discord/handlers.py tests/test_spontaneous.py
git commit -m "feat(discord): add spontaneous memory recall trigger"
```

---

### Task 5: Twitch handler — trigger mémoire spontané

**Files:**
- Modify: `bot/twitch/handlers.py:116-137` (spontaneous block)
- Modify: `bot/twitch/handlers.py:428-476` (`_spontaneous_respond_twitch`)
- Test: `tests/test_spontaneous.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_spontaneous.py`:

```python
@pytest.mark.asyncio
async def test_spontaneous_memory_twitch():
    """Memory recall works on Twitch handler."""
    from bot.twitch.handlers import _spontaneous_respond_twitch
    bot = make_bot_for_spontaneous()
    bot._channel_ids = {"testchannel": "123"}
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_channel)

    await _spontaneous_respond_twitch(
        bot, "testchannel", "123", "TestUser", "je vais jouer",
        recall_memory="joue à Apex",
    )

    complete_call = bot.openai.complete.call_args
    user_content = complete_call.args[1][0]["content"]
    assert "Souvenir qui te revient" in user_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_spontaneous.py::test_spontaneous_memory_twitch -v`
Expected: FAIL (signature mismatch)

- [ ] **Step 3: Modify _spontaneous_respond_twitch()**

In `bot/twitch/handlers.py`, modify `_spontaneous_respond_twitch` (line 428):

Replace the signature:
```python
async def _spontaneous_respond_twitch(
    bot: "WallyTwitch", channel_name: str, channel_id: str,
    author: str, content: str,
) -> None:
```
With:
```python
async def _spontaneous_respond_twitch(
    bot: "WallyTwitch", channel_name: str, channel_id: str,
    author: str, content: str,
    recall_memory: str | None = None,
) -> None:
```

Replace the system_prompt build (lines 436-443):
```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```
With:
```python
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
```

Replace the user_content build (lines 445-451):
```python
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + prelude_block
            + f"\n[{author}]: {content}"
        )
```
With:
```python
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{author}. Évoque-le naturellement.\n\n"
            )
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + recall_block
            + prelude_block
            + f"\n[{author}]: {content}"
        )
```

Add logging after the existing `logger.info` (line 473):
```python
        if recall_memory:
            logger.info("Memory recall for {user} on Twitch: {mem}", user=author, mem=recall_memory[:80])
```

- [ ] **Step 4: Modify the spontaneous block in handle_message_twitch**

In `bot/twitch/handlers.py`, modify the spontaneous block (lines 116-137).

Replace:
```python
    # Spontaneous intervention (Twitch)
    if bot.config.bot.spontaneous_twitch_enabled:
        import time as _time
        state = bot.emotion.get_state()
        trigger_type = _check_spontaneous_trigger(
            content,
            curiosity=state.get("curiosity", 0.0),
            anger=state.get("anger", 0.0),
            boredom=state.get("boredom", 0.0),
        )
        if trigger_type:
            now = _time.time()
            cooldown = bot.config.bot.spontaneous_cooldown_seconds
            if now - _spontaneous_cooldowns.get(channel_id, 0) >= cooldown:
                prob = (
                    bot.config.bot.spontaneous_passion_probability
                    if trigger_type == "passion"
                    else bot.config.bot.spontaneous_probability
                )
                if random.random() < prob:
                    _spontaneous_cooldowns[channel_id] = now
                    _fire(_spontaneous_respond_twitch(bot, channel_name, channel_id, author, content))
```

With:
```python
    # Spontaneous intervention (Twitch)
    if bot.config.bot.spontaneous_twitch_enabled:
        import time as _time
        state = bot.emotion.get_state()
        trigger_type = _check_spontaneous_trigger(
            content,
            curiosity=state.get("curiosity", 0.0),
            anger=state.get("anger", 0.0),
            boredom=state.get("boredom", 0.0),
        )
        now = _time.time()
        cooldown = bot.config.bot.spontaneous_cooldown_seconds
        cooldown_ok = now - _spontaneous_cooldowns.get(channel_id, 0) >= cooldown

Also add a module-level dict (near existing `_spontaneous_cooldowns` in twitch/handlers.py):

```python
_memory_check_cooldowns: dict[str, float] = {}
```

```python
        if trigger_type and cooldown_ok:
            prob = (
                bot.config.bot.spontaneous_passion_probability
                if trigger_type == "passion"
                else bot.config.bot.spontaneous_probability
            )
            if random.random() < prob:
                _spontaneous_cooldowns[channel_id] = now
                _fire(_spontaneous_respond_twitch(bot, channel_name, channel_id, author, content))
        elif not trigger_type and cooldown_ok:
            if now - _memory_check_cooldowns.get(channel_id, 0) >= 60:
                _memory_check_cooldowns[channel_id] = now
                match = await bot.memory.search_top_match("twitch", author, content)
                if match and match[1] >= bot.config.bot.memory_recall_min_score:
                    if random.random() < bot.config.bot.spontaneous_memory_probability:
                        _spontaneous_cooldowns[channel_id] = now
                        _fire(_spontaneous_respond_twitch(
                            bot, channel_name, channel_id, author, content,
                            recall_memory=match[0],
                        ))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_spontaneous.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add bot/twitch/handlers.py tests/test_spontaneous.py
git commit -m "feat(twitch): add spontaneous memory recall trigger"
```

---

### Task 6: Validation finale

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass, including all 12 new tests

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from bot.discord.handlers import handle_message; from bot.twitch.handlers import handle_message_twitch; from bot.core.memory import MemoryService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Check the prompt file is loadable**

Run: `python -c "from bot.core.prompts import load_prompt; d = load_prompt('memory_recall_directive'); print(repr(d[:50])); assert len(d) > 20; print('OK')"`
Expected: First 50 chars of directive + `OK`

- [ ] **Step 4: Update TODO.md**

Mark the task as done in `TODO.md`:
```
- [x] Références spontanées à la mémoire — Wally évoque un souvenir ancien quand le contexte s'y prête
    > Implémenté le 2026-03-23 : search_top_match() + trigger mémoire spontané Discord/Twitch + directive recall dans build_system_prompt()
```

- [ ] **Step 5: Final commit**

```bash
git add TODO.md
git commit -m "docs: mark spontaneous memory recall as done"
```
