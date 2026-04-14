# Streaming Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream LLM responses progressively into Discord messages via edits, and add Twitch reply-to-message support.

**Architecture:** Add `complete_stream()` to the LLM abstraction layer (OpenAI streaming API + Anthropic streaming API). In Discord `_respond()`, replace the non-tool `complete()` call with a streaming flow: send a `"…"` placeholder immediately, then edit it with accumulated tokens every second. For Twitch, add `reply_parent_message_id` to the Helix API and wire it from `ChatMessageData`.

**Tech Stack:** OpenAI Python SDK (stream=True), Anthropic SDK (messages.stream), discord.py (message.edit), twitchio v2 IRC + Helix API

---

## File Map

| File | Change |
|------|--------|
| `bot/core/llm/base.py` | Add `complete_stream()` abstract method |
| `bot/core/llm/openai_client.py` | Implement `complete_stream()` (Chat Completions; Responses API models yield via `complete()`) |
| `bot/core/llm/claude_client.py` | Implement `complete_stream()` via `messages.stream()` |
| `bot/discord/handlers.py` | Add `_stream_to_discord()` helper; wire it in `_respond()` non-tool path + spontaneous path |
| `bot/twitch/events.py` | Add `message_id` field to `ChatMessageData` |
| `bot/twitch/api.py` | Add `reply_parent_message_id: str \| None` param to `send_message()` |
| `bot/twitch/handlers.py` | Use reply for home channel; `@{author}` prefix for guest IRC channels |
| `tests/test_openai_client.py` | Tests for `complete_stream()` |
| `tests/test_twitch_api.py` | Tests for `reply_parent_message_id` |
| `tests/test_discord_handlers.py` | Tests for streaming path in `_respond()` |

---

### Task 1: Add `complete_stream()` to BaseLLMClient

**Files:**
- Modify: `bot/core/llm/base.py`
- Test: `tests/test_openai_client.py` (step 2 verifies ABC contract)

- [ ] **Step 1: Add the abstract method**

In `bot/core/llm/base.py`, add this import at the top and the abstract method after `complete_structured`:

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional
```

Then append after the `complete_structured` method:

```python
    @abstractmethod
    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace: Any = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a text completion as an async generator of text chunks.

        Yields text deltas as they arrive from the model.
        On error, yields FALLBACK_RESPONSE as a single chunk and stops.
        Implementations that do not support native streaming (e.g. Responses API
        models) yield the full response as a single chunk.
        """
```

- [ ] **Step 2: Run type-check**

```bash
cd /opt/stacks/wally-ai && python -m py_compile bot/core/llm/base.py && echo OK
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/llm/base.py
git commit -m "feat(llm): add complete_stream() abstract method to BaseLLMClient"
```

---

### Task 2: Implement `complete_stream()` in OpenAILLMClient

**Files:**
- Modify: `bot/core/llm/openai_client.py`
- Test: `tests/test_openai_client.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_openai_client.py`, add after the existing tests:

```python
@pytest.mark.asyncio
async def test_complete_stream_yields_chunks():
    """complete_stream() should yield text chunks from streaming API."""
    client, _ = make_client(model="gpt-4o", reasoning_effort=None)

    # Mock streaming chunks
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Bonjour"
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " monde"
    chunk3 = MagicMock()
    chunk3.choices = [MagicMock()]
    chunk3.choices[0].delta.content = None  # final chunk has no content

    async def mock_stream():
        for c in [chunk1, chunk2, chunk3]:
            yield c

    mock_create = AsyncMock(return_value=mock_stream())

    with patch.object(client._client.chat.completions, "create", mock_create):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == ["Bonjour", " monde"]


@pytest.mark.asyncio
async def test_complete_stream_responses_api_yields_single_chunk():
    """Responses API models (o1/o3/o4) yield the full response as one chunk."""
    client, _ = make_client(model="o3", reasoning_effort="medium")
    # complete() should be called and its result yielded as one chunk
    with patch.object(client, "complete", AsyncMock(return_value="full response text")):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
    assert chunks == ["full response text"]


@pytest.mark.asyncio
async def test_complete_stream_error_yields_fallback():
    """On API error, complete_stream() yields FALLBACK_RESPONSE."""
    client, _ = make_client(model="gpt-4o", reasoning_effort=None)
    with patch.object(client._client.chat.completions, "create", AsyncMock(side_effect=Exception("boom"))):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)
    assert chunks == [FALLBACK_RESPONSE]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_openai_client.py::test_complete_stream_yields_chunks -v 2>&1 | tail -5
```
Expected: `FAILED` (AttributeError: `complete_stream` not defined)

- [ ] **Step 3: Implement `complete_stream()` in OpenAILLMClient**

In `bot/core/llm/openai_client.py`, add after the `complete()` method (before `complete_with_tools`):

```python
    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace=None,
    ):
        """Stream completion as text chunks via AsyncGenerator.

        Responses API models (o1/o3/o4) do not use streaming — they yield the
        full response as a single chunk via complete().
        """
        if _uses_responses_api(self._model):
            result = await self.complete(
                system_prompt, messages, purpose=purpose,
                image_urls=image_urls, user_id=user_id, trace=trace,
            )
            yield result
            return

        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, False
            )
            full_messages[-1] = last_msg

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                temperature=self._temperature,
                max_completion_tokens=self._max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            logger.error("OpenAI streaming error: {e}", e=exc)
            yield FALLBACK_RESPONSE
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_openai_client.py::test_complete_stream_yields_chunks tests/test_openai_client.py::test_complete_stream_responses_api_yields_single_chunk tests/test_openai_client.py::test_complete_stream_error_yields_fallback -v 2>&1 | tail -10
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/llm/openai_client.py tests/test_openai_client.py
git commit -m "feat(llm): implement complete_stream() in OpenAILLMClient"
```

---

### Task 3: Implement `complete_stream()` in ClaudeLLMClient

**Files:**
- Modify: `bot/core/llm/claude_client.py`
- Test: new tests in `tests/test_claude_client.py` (create if not exists)

- [ ] **Step 1: Check if test file exists**

```bash
ls /opt/stacks/wally-ai/tests/test_claude_client.py 2>/dev/null && echo EXISTS || echo MISSING
```

- [ ] **Step 2: Write the failing test**

Create (or append to) `tests/test_claude_client.py`:

```python
"""Tests for ClaudeLLMClient.complete_stream()."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncContextManager
from contextlib import asynccontextmanager

from bot.core.llm.claude_client import ClaudeLLMClient
from bot.core.llm.base import FALLBACK_RESPONSE


def make_client():
    db = MagicMock()
    db.log_cost = AsyncMock()
    return ClaudeLLMClient(
        model="claude-sonnet-4-6",
        db=db,
        temperature=0.8,
        max_tokens=1000,
    )


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks():
    """complete_stream() should yield text deltas from Anthropic streaming API."""
    client = make_client()

    async def mock_text_stream():
        for text in ["Salut", " toi", " !"]:
            yield text

    @asynccontextmanager
    async def mock_stream_ctx(*args, **kwargs):
        mock_stream = MagicMock()
        mock_stream.text_stream = mock_text_stream()
        yield mock_stream

    with patch.object(client._client.messages, "stream", mock_stream_ctx):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == ["Salut", " toi", " !"]


@pytest.mark.asyncio
async def test_complete_stream_error_yields_fallback():
    """On error, complete_stream() yields FALLBACK_RESPONSE."""
    client = make_client()

    @asynccontextmanager
    async def boom(*args, **kwargs):
        raise Exception("API error")
        yield  # make it a generator

    with patch.object(client._client.messages, "stream", boom):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == [FALLBACK_RESPONSE]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_claude_client.py::test_complete_stream_yields_chunks -v 2>&1 | tail -5
```
Expected: `FAILED` (AttributeError: `complete_stream` not defined)

- [ ] **Step 4: Implement `complete_stream()` in ClaudeLLMClient**

In `bot/core/llm/claude_client.py`, add this method after `complete()` (before `complete_with_tools`):

```python
    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace=None,
    ):
        """Stream completion as text chunks via Anthropic messages.stream()."""
        claude_messages = _convert_messages_for_claude(messages)
        effective_max = self._max_tokens

        if image_urls and claude_messages:
            last_msg = dict(claude_messages[-1])
            last_msg["content"] = _build_claude_image_content(
                last_msg["content"] if isinstance(last_msg["content"], str) else str(last_msg["content"]),
                image_urls,
            )
            claude_messages[-1] = last_msg

        kwargs = dict(
            model=self._model,
            max_tokens=effective_max,
            system=self._build_system_with_caching(system_prompt),
            messages=claude_messages,
            temperature=self._temperature,
        )

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text_delta in stream.text_stream:
                    yield text_delta
        except Exception as exc:
            logger.error("Claude streaming error: {e}", e=exc)
            yield FALLBACK_RESPONSE
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_claude_client.py -v 2>&1 | tail -10
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/core/llm/claude_client.py tests/test_claude_client.py
git commit -m "feat(llm): implement complete_stream() in ClaudeLLMClient"
```

---

### Task 4: Discord streaming — `_stream_to_discord()` helper + wire in `_respond()`

**Files:**
- Modify: `bot/discord/handlers.py`
- Test: `tests/test_discord_handlers.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_discord_handlers.py`, search for the import section and append the following tests (after existing ones). First check which imports exist:

```bash
head -30 /opt/stacks/wally-ai/tests/test_discord_handlers.py
```

Then add these tests (add any missing imports as needed):

```python
# --- Streaming tests ---

@pytest.mark.asyncio
async def test_stream_to_discord_edits_placeholder():
    """_stream_to_discord sends a placeholder then edits it with streamed text."""
    from bot.discord.handlers import _stream_to_discord
    from bot.core.llm.base import FALLBACK_RESPONSE
    import asyncio

    message = AsyncMock()
    placeholder = AsyncMock()
    placeholder.id = 999
    message.reply = AsyncMock(return_value=placeholder)

    async def fake_stream(*args, **kwargs):
        for chunk in ["Bonjour", " toi", " !"]:
            yield chunk

    llm = MagicMock()
    llm.complete_stream = fake_stream

    full_text, msg = await _stream_to_discord(
        message, llm, "sys", [{"role": "user", "content": "hi"}], None, "discord:123", None
    )

    assert full_text == "Bonjour toi !"
    assert msg is placeholder
    # placeholder.edit should have been called at least once (final edit)
    placeholder.edit.assert_awaited()


@pytest.mark.asyncio
async def test_stream_to_discord_fallback_on_empty():
    """_stream_to_discord uses FALLBACK_RESPONSE when stream yields nothing."""
    from bot.discord.handlers import _stream_to_discord
    from bot.core.llm.base import FALLBACK_RESPONSE

    message = AsyncMock()
    placeholder = AsyncMock()
    message.reply = AsyncMock(return_value=placeholder)

    async def empty_stream(*args, **kwargs):
        return
        yield  # make it a generator

    llm = MagicMock()
    llm.complete_stream = empty_stream

    full_text, msg = await _stream_to_discord(
        message, llm, "sys", [{"role": "user", "content": "hi"}], None, "discord:123", None
    )

    assert full_text == FALLBACK_RESPONSE
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_handlers.py::test_stream_to_discord_edits_placeholder -v 2>&1 | tail -5
```
Expected: `FAILED` (ImportError: cannot import `_stream_to_discord`)

- [ ] **Step 3: Add `_stream_to_discord()` to handlers.py**

In `bot/discord/handlers.py`, add this function **before** `_send_in_parts` (i.e., before line 656). Also add to the top-level imports if `AsyncGenerator` is not already imported:

```python
import asyncio
import time
```
(both likely already imported — verify before adding)

New function to add:

```python
_REACT_TAG_PREFIX_RE = re.compile(r"^\[react:[^\]]+\]\s*")

DISCORD_MSG_LIMIT = 1990  # Safe limit below Discord's 2000 char hard cap
_STREAM_EDIT_INTERVAL = 1.0  # Seconds between intermediate edits


async def _stream_to_discord(
    message: discord.Message,
    llm,
    system_prompt: str,
    openai_messages: list[dict],
    image_urls: list[str] | None,
    user_id: str,
    trace,
) -> tuple[str, discord.Message | None]:
    """Stream LLM response into a Discord message via progressive edits.

    Sends a placeholder '…' reply immediately, then edits it with accumulated
    tokens every _STREAM_EDIT_INTERVAL seconds. Returns (full_text, placeholder_msg).
    On total failure, returns (FALLBACK_RESPONSE, placeholder_msg).
    """
    from bot.core.llm.base import FALLBACK_RESPONSE as _FALLBACK

    placeholder = await message.reply("…")
    full_text = ""
    last_edit = asyncio.get_event_loop().time()

    try:
        async for chunk in llm.complete_stream(
            system_prompt,
            openai_messages,
            purpose="discord_response",
            image_urls=image_urls,
            user_id=user_id,
            trace=trace,
        ):
            full_text += chunk
            now = asyncio.get_event_loop().time()
            if now - last_edit >= _STREAM_EDIT_INTERVAL and full_text.strip() not in ("", "…"):
                display = _REACT_TAG_PREFIX_RE.sub("", full_text)
                try:
                    await placeholder.edit(content=display[:DISCORD_MSG_LIMIT])
                    last_edit = now
                except Exception:
                    pass
    except Exception as exc:
        logger.error("Streaming error in _stream_to_discord: {e}", e=exc)

    if not full_text.strip():
        full_text = _FALLBACK

    # Final edit with clean text (react tag stripped)
    display_final = _REACT_TAG_PREFIX_RE.sub("", full_text)
    try:
        await placeholder.edit(content=display_final[:DISCORD_MSG_LIMIT])
    except Exception:
        pass

    # Handle overflow: send the rest as follow-up messages
    if len(display_final) > DISCORD_MSG_LIMIT:
        rest = display_final[DISCORD_MSG_LIMIT:]
        while rest:
            await asyncio.sleep(0.4)
            try:
                await message.channel.send(rest[:DISCORD_MSG_LIMIT])
            except Exception:
                break
            rest = rest[DISCORD_MSG_LIMIT:]

    return full_text, placeholder
```

- [ ] **Step 4: Wire streaming into `_respond()` — non-tool path**

In `bot/discord/handlers.py`, find the non-tool LLM call block (around line 1055). Replace the current structure:

**Current code (lines ~1055–1092):**
```python
        async with message.channel.typing():
            if tools:
                reply, tools_called = await bot.llm.complete_with_tools(
                    system_prompt, openai_messages, tools, _tool_executor,
                    purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                    trace=trace,
                )
            else:
                reply = await bot.llm.complete(
                    system_prompt, openai_messages, purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                    trace=trace,
                )
                tools_called = []

        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)

        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        for emoji in _reaction_emojis:
            try:
                await message.remove_reaction(emoji, bot.user)
            except Exception:
                pass

        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            except Exception:
                pass

        reply_msg_id = await _send_in_parts(message, reply)
```

**Replace with:**
```python
        if tools:
            async with message.channel.typing():
                reply, tools_called = await bot.llm.complete_with_tools(
                    system_prompt, openai_messages, tools, _tool_executor,
                    purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                    trace=trace,
                )
            react_emoji, reply = _parse_react_tag(reply)
            try:
                await message.remove_reaction("🔍", bot.user)
            except Exception:
                pass
            for emoji in _reaction_emojis:
                try:
                    await message.remove_reaction(emoji, bot.user)
                except Exception:
                    pass
            if react_emoji:
                try:
                    await message.add_reaction(react_emoji)
                except Exception:
                    pass
            reply_msg_id = await _send_in_parts(message, reply)
        else:
            tools_called = []
            full_text, placeholder_msg = await _stream_to_discord(
                message,
                bot.llm,
                system_prompt,
                openai_messages,
                image_urls or None,
                f"discord:{message.author.id}",
                trace,
            )
            react_emoji, reply = _parse_react_tag(full_text)
            try:
                await message.remove_reaction("🔍", bot.user)
            except Exception:
                pass
            for emoji in _reaction_emojis:
                try:
                    await message.remove_reaction(emoji, bot.user)
                except Exception:
                    pass
            if react_emoji:
                try:
                    await message.add_reaction(react_emoji)
                except Exception:
                    pass
            reply_msg_id = placeholder_msg.id if placeholder_msg else None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_handlers.py::test_stream_to_discord_edits_placeholder tests/test_discord_handlers.py::test_stream_to_discord_fallback_on_empty -v 2>&1 | tail -10
```
Expected: 2 PASSED

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_discord_handlers.py -v 2>&1 | tail -20
```
Expected: all existing tests still pass

- [ ] **Step 7: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/discord/handlers.py tests/test_discord_handlers.py
git commit -m "feat(discord): stream LLM responses via progressive message edits"
```

---

### Task 5: Twitch reply support

**Files:**
- Modify: `bot/twitch/events.py` — add `message_id` to `ChatMessageData`
- Modify: `bot/twitch/api.py` — add `reply_parent_message_id` param
- Modify: `bot/twitch/handlers.py` — use reply for home channel; `@{author}` for guest channels
- Test: `tests/test_twitch_api.py`

- [ ] **Step 1: Write failing tests for TwitchAPI reply support**

In `tests/test_twitch_api.py`, append after existing tests:

```python
@pytest.mark.asyncio
async def test_send_message_with_reply_parent():
    """reply_parent_message_id is included in the JSON body when provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello", reply_parent_message_id="msg-abc-123")
    body = mock_http.post.call_args.kwargs["json"]
    assert body["reply_parent_message_id"] == "msg-abc-123"


@pytest.mark.asyncio
async def test_send_message_without_reply_parent_omits_field():
    """reply_parent_message_id is NOT in the JSON body when not provided."""
    api = make_api()
    ok = make_http_response(200)
    with patch("bot.twitch.api.httpx.AsyncClient") as MockClient:
        mock_http = MockClient.return_value.__aenter__.return_value
        mock_http.post = AsyncMock(return_value=ok)
        await api.send_message("hello")
    body = mock_http.post.call_args.kwargs["json"]
    assert "reply_parent_message_id" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_api.py::test_send_message_with_reply_parent -v 2>&1 | tail -5
```
Expected: `FAILED`

- [ ] **Step 3: Add `reply_parent_message_id` to `TwitchAPI.send_message()`**

In `bot/twitch/api.py`, modify `send_message()` signature and body:

**Current:**
```python
    async def send_message(self, text: str, broadcaster_id: Optional[str] = None) -> None:
```

**Replace with:**
```python
    async def send_message(
        self,
        text: str,
        broadcaster_id: Optional[str] = None,
        reply_parent_message_id: Optional[str] = None,
    ) -> None:
```

And in the JSON payload (currently `"message": text`), add the reply field conditionally. Find:

```python
                        json={
                            "broadcaster_id": target,
                            "sender_id": self._bot_id,
                            "message": text,
                        },
```

Replace with:

```python
                        json={k: v for k, v in {
                            "broadcaster_id": target,
                            "sender_id": self._bot_id,
                            "message": text,
                            "reply_parent_message_id": reply_parent_message_id,
                        }.items() if v is not None},
```

- [ ] **Step 4: Add `message_id` to `ChatMessageData` in `bot/twitch/events.py`**

Find `ChatMessageData`:

```python
class ChatMessageData:
    __slots__ = "chatter", "message", "broadcaster"

    def __init__(self, client, data: dict):
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )
```

Replace with:

```python
class ChatMessageData:
    __slots__ = "chatter", "message", "broadcaster", "message_id"

    def __init__(self, client, data: dict):
        self.chatter = client.client.create_user(
            int(data["chatter_user_id"]), data["chatter_user_login"]
        )
        self.message = _ChatMessageText(data["message"])
        self.broadcaster = client.client.create_user(
            int(data["broadcaster_user_id"]), data["broadcaster_user_login"]
        )
        self.message_id: str = data.get("message_id", "")
```

- [ ] **Step 5: Wire reply into `bot/twitch/handlers.py`**

In `handle_message()`, find the reply-send block for the main response (around line 427–436):

```python
        if channel_name in bot._channel_ids:
            # Chaîne invitée : envoi via IRC (pas d'autorisation broadcaster requise)
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(reply)
            else:
                logger.warning("IRC non connecté pour {ch}, réponse ignorée", ch=channel_name)
        else:
            # Chaîne home : envoi via Helix API
            await bot.twitch_api.send_message(text=reply)
```

Replace with:

```python
        if channel_name in bot._channel_ids:
            # Chaîne invitée : envoi via IRC — mention @author pour simuler une réponse
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(f"@{author} {reply}")
            else:
                logger.warning("IRC non connecté pour {ch}, réponse ignorée", ch=channel_name)
        else:
            # Chaîne home : envoi via Helix API avec reply thread
            msg_id = getattr(payload, "message_id", None) or None
            await bot.twitch_api.send_message(
                text=reply,
                reply_parent_message_id=msg_id,
            )
```

- [ ] **Step 6: Run all Twitch-related tests**

```bash
cd /opt/stacks/wally-ai && python -m pytest tests/test_twitch_api.py tests/test_twitch_handlers.py tests/test_twitch_events.py -v 2>&1 | tail -20
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
cd /opt/stacks/wally-ai
git add bot/twitch/events.py bot/twitch/api.py bot/twitch/handlers.py tests/test_twitch_api.py
git commit -m "feat(twitch): add reply-to-message support via Helix API and IRC @mention"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /opt/stacks/wally-ai && python -m pytest --tb=short -q 2>&1 | tail -20
```
Expected: all existing tests pass + new tests pass (no regressions)

- [ ] **Step 2: Type-check key files**

```bash
cd /opt/stacks/wally-ai && python -m py_compile bot/core/llm/base.py bot/core/llm/openai_client.py bot/core/llm/claude_client.py bot/discord/handlers.py bot/twitch/api.py bot/twitch/events.py bot/twitch/handlers.py && echo ALL OK
```
Expected: `ALL OK`

- [ ] **Step 3: Commit verification tag**

```bash
cd /opt/stacks/wally-ai
git commit --allow-empty -m "chore: streaming responses feature complete — all tests passing"
```
