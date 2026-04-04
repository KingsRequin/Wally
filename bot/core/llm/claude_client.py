# bot/core/llm/claude_client.py
from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Callable, Awaitable

from loguru import logger

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE
from bot.core.tracing import create_generation

if TYPE_CHECKING:
    from bot.db.database import Database

# Cost per 1M tokens (input, output) in USD
CLAUDE_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-5": (15.0, 75.0),
}

CLAUDE_FALLBACK_COST = (3.0, 15.0)

# Cached input tokens are billed at 10% of the normal input rate for Claude
CLAUDE_CACHE_DISCOUNT = 0.1


def _estimate_claude_cost(
    model: str, input_tokens: int, output_tokens: int,
    cache_read_tokens: int = 0, cache_creation_tokens: int = 0,
) -> float:
    costs = CLAUDE_MODEL_COSTS.get(model) or next(
        (v for k, v in sorted(CLAUDE_MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        CLAUDE_FALLBACK_COST,
    )
    # Non-cached input = total input - cache_read - cache_creation
    # Clamp to 0 — in rare edge cases Anthropic may report cache_read + cache_creation
    # slightly above input_tokens (rounding), which would produce a negative cost.
    non_cached = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)
    return (
        non_cached * costs[0]
        + cache_read_tokens * costs[0] * CLAUDE_CACHE_DISCOUNT
        + cache_creation_tokens * costs[0] * 1.25  # cache writes cost 25% more
        + output_tokens * costs[1]
    ) / 1_000_000


def _convert_tools_to_claude(tools: list[dict]) -> list[dict]:
    """Convert OpenAI Chat Completions tool format to Claude tool format.

    OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Claude: {"name": ..., "description": ..., "input_schema": ...}
    """
    converted = []
    for tool in tools:
        if "function" in tool:
            fn = tool["function"]
            converted.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            converted.append(tool)
    return converted


def _build_claude_image_content(text: str, image_urls: list[str]) -> list[dict]:
    """Build Claude-format content blocks with images."""
    content: list[dict] = []
    for url in image_urls:
        content.append({
            "type": "image",
            "source": {"type": "url", "url": url},
        })
    content.append({"type": "text", "text": text})
    return content


def _convert_messages_for_claude(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to Claude format.

    Filters out system messages (handled separately) and ensures
    content is in the right format.
    """
    converted = []
    for msg in messages:
        if msg.get("role") == "system":
            continue
        converted.append({"role": msg["role"], "content": msg["content"]})
    return converted


class ClaudeLLMClient(BaseLLMClient):
    """Anthropic Claude LLM client with prompt caching support."""

    def __init__(
        self,
        model: str,
        db: "Database",
        temperature: float = 1.0,
        max_tokens: int = 1000,
        thinking_type: str = "disabled",
        thinking_budget_tokens: int = 10000,
        thinking_effort: str = "medium",
        **kwargs,
    ):
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_type = thinking_type
        self._thinking_budget_tokens = thinking_budget_tokens
        self._thinking_effort = thinking_effort
        api_key = os.environ.get("ANTHROPIC_API_KEY", "dummy-key-for-testing")

        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    @property
    def temperature(self) -> float:
        return self._temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        self._temperature = value

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        self._max_tokens = value

    @property
    def thinking_type(self) -> str:
        return self._thinking_type

    @thinking_type.setter
    def thinking_type(self, value: str) -> None:
        self._thinking_type = value

    @property
    def thinking_budget_tokens(self) -> int:
        return self._thinking_budget_tokens

    @thinking_budget_tokens.setter
    def thinking_budget_tokens(self, value: int) -> None:
        self._thinking_budget_tokens = value

    @property
    def thinking_effort(self) -> str:
        return self._thinking_effort

    @thinking_effort.setter
    def thinking_effort(self, value: str) -> None:
        self._thinking_effort = value

    def _build_thinking_param(self) -> dict | None:
        """Build the thinking parameter for the API call, or None if disabled."""
        if self._thinking_type == "adaptive":
            return {"type": "adaptive"}
        elif self._thinking_type == "enabled":
            return {"type": "enabled", "budget_tokens": self._thinking_budget_tokens}
        return None

    def _build_output_config(self) -> dict | None:
        """Build output_config with effort level.

        Only valid for adaptive thinking — the Anthropic API documents output_config.effort
        exclusively for adaptive mode. Injecting it for enabled (fixed budget_tokens) has
        no documented effect and risks a 400 on non-high effort values.
        """
        if self._thinking_type == "adaptive" and self._thinking_effort != "high":
            return {"effort": self._thinking_effort}
        return None

    async def _log_usage(
        self, usage, purpose: str, user_id: str | None = None,
        trace=None, messages=None, output_text=None,
    ) -> float:
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cost = _estimate_claude_cost(
            self._model, input_tokens, output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )
        create_generation(
            trace,
            name=purpose,
            model=self._model,
            input=messages,
            output=output_text,
            usage={"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
            metadata={"purpose": purpose, "user_id": user_id, "temperature": self._temperature},
        )
        cache_info = ""
        if cache_read or cache_creation:
            cache_info = f" (cache: {cache_read}read/{cache_creation}write)"
        logger.info(
            "Claude {model} — {inp}in/{out}out tokens{cache}, ${cost:.6f} [{purpose}]",
            model=self._model, inp=input_tokens, out=output_tokens,
            cache=cache_info, cost=cost, purpose=purpose,
        )
        return cost

    def _build_system_with_caching(self, system_prompt: str) -> list[dict]:
        """Build system prompt with cache_control for Anthropic prompt caching."""
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def _call_with_retry(self, call_fn, purpose: str, fallback=None):
        """Execute an API call with exponential backoff retry logic."""
        from anthropic import RateLimitError, APIStatusError

        for attempt in range(3):
            try:
                return await call_fn()
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited by Anthropic, retrying in {w}s (attempt {a}/3)",
                    w=wait, a=attempt + 1,
                )
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        "Anthropic server error {code}, retrying in {w}s",
                        code=exc.status_code, w=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Anthropic API error {code}: {e}",
                        code=exc.status_code, e=exc,
                    )
                    if fallback is not None:
                        return fallback
                    break
            except Exception as exc:
                logger.error("Anthropic unexpected error: {e}", e=exc)
                if fallback is not None:
                    return fallback
                break
        return fallback

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
        trace=None,
    ) -> str:
        claude_messages = _convert_messages_for_claude(messages)
        effective_max = max_tokens or self._max_tokens

        if image_urls and claude_messages:
            last_msg = dict(claude_messages[-1])
            last_msg["content"] = _build_claude_image_content(
                last_msg["content"] if isinstance(last_msg["content"], str) else str(last_msg["content"]),
                image_urls,
            )
            claude_messages[-1] = last_msg

        fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
        thinking = self._build_thinking_param()
        output_config = self._build_output_config()

        async def _call():
            kwargs = dict(
                model=self._model,
                max_tokens=effective_max,
                system=self._build_system_with_caching(system_prompt),
                messages=claude_messages,
            )
            if thinking:
                kwargs["thinking"] = thinking
                # temperature must be 1 when thinking is enabled
                kwargs["temperature"] = 1
            else:
                kwargs["temperature"] = self._temperature
            if output_config:
                kwargs["output_config"] = output_config
            response = await self._client.messages.create(**kwargs)
            # Extract text blocks only (skip thinking blocks)
            text_blocks = [b for b in response.content if b.type == "text"]
            text = text_blocks[0].text if text_blocks else ""
            result_text = text.strip() if text else fallback
            await self._log_usage(
                response.usage, purpose, user_id=user_id,
                trace=trace, messages=claude_messages, output_text=result_text,
            )
            return result_text

        result = await self._call_with_retry(_call, purpose, fallback=fallback)
        return result if result is not None else fallback

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace=None,
        tools: list[dict] | None = None,
        tool_executor=None,
    ):
        """Stream completion as text chunks via Anthropic messages.stream().

        When tools are provided, falls back to complete_with_tools() and yields
        the result as a single chunk (Claude streaming with tool calls is complex).
        """
        if tools and tool_executor:
            # Fallback: use complete_with_tools, yield result as single chunk
            try:
                reply, _ = await self.complete_with_tools(
                    system_prompt, messages, tools, tool_executor,
                    purpose=purpose, image_urls=image_urls, user_id=user_id, trace=trace,
                )
            except Exception as exc:
                logger.error("Claude complete_with_tools fallback error: {e}", e=exc)
                reply = FALLBACK_RESPONSE
            yield reply
            return

        # True streaming (no tools)
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

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace=None,
    ) -> tuple[str, list[str]]:
        claude_messages = _convert_messages_for_claude(messages)
        claude_tools = _convert_tools_to_claude(tools)
        tools_called: list[str] = []

        if image_urls and claude_messages:
            last_msg = dict(claude_messages[-1])
            last_msg["content"] = _build_claude_image_content(
                last_msg["content"] if isinstance(last_msg["content"], str) else str(last_msg["content"]),
                image_urls,
            )
            claude_messages[-1] = last_msg

        fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_creation = 0

        from anthropic import RateLimitError, APIStatusError

        system = self._build_system_with_caching(system_prompt)
        thinking = self._build_thinking_param()
        output_config = self._build_output_config()
        base_kwargs = dict(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            tools=claude_tools,
        )
        if thinking:
            base_kwargs["thinking"] = thinking
            base_kwargs["temperature"] = 1
        else:
            base_kwargs["temperature"] = self._temperature
        if output_config:
            base_kwargs["output_config"] = output_config

        # First call with retry (transient errors on initial call)
        response = None
        for attempt in range(3):
            try:
                response = await self._client.messages.create(
                    messages=claude_messages,
                    **base_kwargs,
                )
                break
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("Rate limited by Anthropic (tools), retrying in {w}s", w=wait)
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("Anthropic server error {code} (tools), retrying in {w}s", code=exc.status_code, w=wait)
                    await asyncio.sleep(wait)
                else:
                    logger.error("Anthropic API error {code} (tools): {e}", code=exc.status_code, e=exc)
                    return fallback, tools_called
            except Exception as exc:
                logger.error("Anthropic unexpected error (tools): {e}", e=exc)
                return fallback, tools_called

        if response is None:
            logger.error("Anthropic API (tools) failed after 3 retries")
            return fallback, tools_called

        try:
            if response.usage:
                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens
                total_cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
                total_cache_creation += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

            max_iterations = 3
            for _ in range(max_iterations):
                # Check for tool_use blocks
                tool_use_blocks = [
                    block for block in response.content
                    if block.type == "tool_use"
                ]
                if not tool_use_blocks:
                    break

                # Append assistant response (full content including thinking + tool_use blocks)
                content_blocks = []
                for b in response.content:
                    if b.type == "thinking":
                        content_blocks.append({"type": "thinking", "thinking": b.thinking, "signature": b.signature})
                    elif b.type == "text":
                        content_blocks.append({"type": "text", "text": b.text})
                    elif b.type == "tool_use":
                        content_blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                claude_messages.append({"role": "assistant", "content": content_blocks})

                # Execute each tool and build tool_result blocks
                tool_results = []
                for tu in tool_use_blocks:
                    tools_called.append(tu.name)
                    result = await tool_executor(tu.name, json.dumps(tu.input))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result,
                    })

                claude_messages.append({"role": "user", "content": tool_results})

                response = await self._client.messages.create(
                    messages=claude_messages,
                    **base_kwargs,
                )

                if response.usage:
                    total_input += response.usage.input_tokens
                    total_output += response.usage.output_tokens
                    total_cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
                    total_cache_creation += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

            # Extract final text
            text_blocks = [b for b in response.content if b.type == "text"]
            text = text_blocks[0].text.strip() if text_blocks else ""

            cost = _estimate_claude_cost(
                self._model, total_input, total_output,
                cache_read_tokens=total_cache_read,
                cache_creation_tokens=total_cache_creation,
            )
            create_generation(
                trace,
                name=purpose,
                model=self._model,
                input=claude_messages,
                output=text,
                usage={"input": total_input, "output": total_output, "total": total_input + total_output},
                metadata={"purpose": purpose, "user_id": user_id, "temperature": self._temperature},
            )
            cache_info = ""
            if total_cache_read or total_cache_creation:
                cache_info = f" (cache: {total_cache_read}read/{total_cache_creation}write)"
            logger.info(
                "Claude {model} (tools) — {inp}in/{out}out tokens{cache}, ${cost:.6f} [{purpose}]",
                model=self._model, inp=total_input, out=total_output,
                cache=cache_info, cost=cost, purpose=purpose,
            )
            return text or fallback, tools_called

        except Exception as exc:
            logger.error("Anthropic API (tools) error: {e}", e=exc)
            return fallback, tools_called

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
        trace=None,
    ) -> dict:
        """Generate structured JSON output using a tool-based approach.

        Claude doesn't have native JSON schema mode like OpenAI, so we use
        a tool with the schema as input_schema and force the model to call it.
        """
        claude_messages = _convert_messages_for_claude(messages)

        # Create a tool that captures the structured output
        structured_tool = {
            "name": schema_name,
            "description": f"Output the structured {schema_name} data.",
            "input_schema": schema,
        }

        # Augment system prompt to instruct the model to use the tool
        augmented_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: You MUST use the '{schema_name}' tool to return your response. "
            f"Do not write a text response — call the tool with the structured data."
        )

        from anthropic import RateLimitError, APIStatusError

        for attempt in range(3):
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens or 4096,
                    temperature=self._temperature,
                    system=self._build_system_with_caching(augmented_system),
                    messages=claude_messages,
                    tools=[structured_tool],
                    tool_choice={"type": "tool", "name": schema_name},
                )

                if response.usage:
                    await self._log_usage(
                        response.usage, purpose, user_id=user_id,
                        trace=trace, messages=claude_messages, output_text=str(response.content),
                    )

                # Extract the tool_use block
                for block in response.content:
                    if block.type == "tool_use" and block.name == schema_name:
                        return block.input

                raise RuntimeError(
                    f"Claude structured output: no tool_use block found "
                    f"(stop_reason={response.stop_reason!r})"
                )

            except RuntimeError:
                raise
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited by Anthropic (structured), retrying in {w}s (attempt {a}/3)",
                    w=wait, a=attempt + 1,
                )
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        "Anthropic server error {code} (structured), retrying in {w}s",
                        code=exc.status_code, w=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Anthropic API error {code} (structured): {e}",
                        code=exc.status_code, e=exc,
                    )
                    break
            except Exception as exc:
                logger.error("Anthropic unexpected error (structured): {e}", e=exc)
                break

        raise RuntimeError(
            f"complete_structured failed after 3 attempts (model={self._model!r})"
        )
