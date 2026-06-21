# bot/core/llm/openai_client.py
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

from loguru import logger
import os

from openai import AsyncOpenAI, RateLimitError, APIStatusError

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE, FALLBACK_IMAGE_RESPONSE

if TYPE_CHECKING:
    from bot.db.database import Database

_RESPONSES_API_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _uses_responses_api(model: str) -> bool:
    return any(model.startswith(p) for p in _RESPONSES_API_PREFIXES)


# Cost per 1M tokens (input, output) in USD
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-5": (2.0, 8.0),
    "gpt-5-mini": (0.15, 0.60),
    "gpt-5-nano": (0.10, 0.40),
    "gpt-5-pro": (10.0, 40.0),
    "gpt-5.1": (2.0, 8.0),
    "gpt-5.2": (2.0, 8.0),
    "gpt-5.3": (2.0, 8.0),
    "gpt-5.4": (2.0, 8.0),
    "gpt-5.4-mini": (0.15, 0.60),
    "gpt-5.4-nano": (0.10, 0.40),
    "gpt-5.4-pro": (10.0, 40.0),
}

FALLBACK_COST = (5.0, 15.0)

IMAGE_COSTS: dict[str, dict[tuple[str, str], float]] = {
    "gpt-image-1.5": {
        ("low", "1024x1024"): 0.009, ("low", "1024x1536"): 0.013, ("low", "1536x1024"): 0.013,
        ("medium", "1024x1024"): 0.034, ("medium", "1024x1536"): 0.05, ("medium", "1536x1024"): 0.05,
        ("high", "1024x1024"): 0.133, ("high", "1024x1536"): 0.20, ("high", "1536x1024"): 0.20,
    },
    "gpt-image-1": {
        ("low", "1024x1024"): 0.011, ("low", "1024x1536"): 0.016, ("low", "1536x1024"): 0.016,
        ("medium", "1024x1024"): 0.042, ("medium", "1024x1536"): 0.063, ("medium", "1536x1024"): 0.063,
        ("high", "1024x1024"): 0.167, ("high", "1024x1536"): 0.25, ("high", "1536x1024"): 0.25,
    },
    "gpt-image-1-mini": {
        ("low", "1024x1024"): 0.005, ("low", "1024x1536"): 0.0075, ("low", "1536x1024"): 0.0075,
        ("medium", "1024x1024"): 0.019, ("medium", "1024x1536"): 0.0285, ("medium", "1536x1024"): 0.0285,
        ("high", "1024x1024"): 0.076, ("high", "1024x1536"): 0.114, ("high", "1536x1024"): 0.114,
    },
}

DATA_GALLERY_DIR = Path("data/gallery")


def _tools_for_responses_api(tools: list[dict]) -> list[dict]:
    """Convert Chat Completions tool format to Responses API format."""
    converted = []
    for tool in tools:
        if "function" in tool:
            fn = tool["function"]
            converted.append({
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        else:
            converted.append(tool)
    return converted


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    costs = MODEL_COSTS.get(model) or next(
        (v for k, v in sorted(MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        FALLBACK_COST,
    )
    non_cached = input_tokens - cached_input_tokens
    return (
        non_cached * costs[0]
        + cached_input_tokens * costs[0] * 0.5
        + output_tokens * costs[1]
    ) / 1_000_000


class OpenAILLMClient(BaseLLMClient):
    """OpenAI LLM client supporting both Chat Completions and Responses API."""

    def __init__(
        self,
        model: str,
        db: "Database",
        temperature: float = 0.8,
        max_tokens: int = 1000,
        reasoning_effort: str = "medium",
        text_verbosity: str = "medium",
    ):
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._text_verbosity = text_verbosity
        api_key = os.environ.get("OPENAI_API_KEY", "dummy-key-for-testing")
        self._client = AsyncOpenAI(api_key=api_key)

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
    def reasoning_effort(self) -> str:
        return self._reasoning_effort

    @reasoning_effort.setter
    def reasoning_effort(self, value: str) -> None:
        self._reasoning_effort = value

    @property
    def text_verbosity(self) -> str:
        return self._text_verbosity

    @text_verbosity.setter
    def text_verbosity(self, value: str) -> None:
        self._text_verbosity = value

    def _build_image_content(
        self, text: str, image_urls: list[str], use_responses_api: bool
    ) -> list[dict]:
        if use_responses_api:
            content = [{"type": "input_text", "text": text}]
            for url in image_urls:
                content.append({"type": "input_image", "image_url": url})
        else:
            content = [{"type": "text", "text": text}]
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return content

    async def _complete_responses_api(
        self, messages: list[dict], purpose: str,
        user_id: str | None = None, max_tokens: int | None = None,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "input": messages,
        }
        uses_reasoning = self._reasoning_effort and self._reasoning_effort != "none"
        if uses_reasoning:
            kwargs["reasoning"] = {"effort": self._reasoning_effort}
        if self._text_verbosity:
            kwargs["text"] = {"format": {"type": "text"}, "verbosity": self._text_verbosity}
        effective_max = max_tokens or self._max_tokens
        if effective_max and not uses_reasoning:
            # Skip max_output_tokens when reasoning is active: the Responses API
            # shares the budget between reasoning and text, which can starve the
            # visible response on small models.
            kwargs["max_output_tokens"] = effective_max
        response = await self._client.responses.create(**kwargs)
        text = response.output_text
        if response.usage:
            try:
                cached = response.usage.input_tokens_details.cached_tokens or 0
            except (AttributeError, TypeError):
                cached = 0
            cost = estimate_cost(
                self._model, response.usage.input_tokens, response.usage.output_tokens,
                cached_input_tokens=cached,
            )
            logger.info(
                "OpenAI {model} (Responses) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=self._model, inp=response.usage.input_tokens,
                out=response.usage.output_tokens, cost=cost, purpose=purpose,
            )
        return text

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        effective_max_tokens = max_tokens or self._max_tokens
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, _uses_responses_api(self._model)
            )
            full_messages[-1] = last_msg

        if _uses_responses_api(self._model):
            fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
            for attempt in range(3):
                try:
                    return await self._complete_responses_api(
                        full_messages, purpose, user_id=user_id, max_tokens=effective_max_tokens,
                    )
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (Responses API), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI Responses API server error {code}, retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error("OpenAI Responses API error {code}: {e}", code=exc.status_code, e=exc)
                        return fallback
                except Exception as exc:
                    logger.error("OpenAI Responses API error: {e}", e=exc)
                    return fallback
            logger.error("OpenAI Responses API failed after 3 retries")
            return fallback

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    temperature=self._temperature,
                    max_completion_tokens=effective_max_tokens,
                )
                usage = response.usage
                try:
                    cached = usage.prompt_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    cached = 0
                cost = estimate_cost(
                    self._model, usage.prompt_tokens, usage.completion_tokens,
                    cached_input_tokens=cached,
                )
                logger.info(
                    "OpenAI {model} — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=self._model, inp=usage.prompt_tokens,
                    out=usage.completion_tokens, cost=cost, purpose=purpose,
                )
                return response.choices[0].message.content.strip()

            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited by OpenAI, retrying in {w}s (attempt {a}/3)",
                    w=wait, a=attempt + 1,
                )
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        "OpenAI server error {code}, retrying in {w}s",
                        code=exc.status_code, w=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error {code}: {e}", code=exc.status_code, e=exc)
                    break
            except Exception as exc:
                logger.error("OpenAI unexpected error: {e}", e=exc)
                break

        return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        tools: list[dict] | None = None,
        tool_executor=None,
    ):
        """Stream completion as text chunks, with optional tool call support.

        Responses API models yield the full response as a single chunk via complete().
        When tools are provided and the model requests tool calls, executes them
        and continues streaming the final response.
        """
        if _uses_responses_api(self._model):
            result = await self.complete(
                system_prompt, messages, purpose=purpose,
                image_urls=image_urls, user_id=user_id,
            )
            yield result
            return

        current_messages = [{"role": "system", "content": system_prompt}] + list(messages)

        if image_urls:
            last_msg = dict(current_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, False
            )
            current_messages[-1] = last_msg

        try:
            while True:
                create_kwargs: dict = dict(
                    model=self._model,
                    messages=current_messages,
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                    stream=True,
                )
                if tools:
                    create_kwargs["tools"] = tools

                stream = await self._client.chat.completions.create(**create_kwargs)

                text_parts: list[str] = []
                tool_calls_acc: dict[int, dict] = {}
                finish_reason: str | None = None

                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason
                    delta = choice.delta

                    if delta.content:
                        text_parts.append(delta.content)
                        yield delta.content

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] += tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments

                if finish_reason == "tool_calls" and tool_calls_acc and tool_executor:
                    sorted_tcs = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                    current_messages.append({
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]},
                            }
                            for tc in sorted_tcs
                        ],
                    })
                    for tc in sorted_tcs:
                        result = await tool_executor(tc["name"], tc["arguments"])
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })
                    # Continue loop: next iteration streams the final response after tool calls
                else:
                    break

        except Exception as exc:
            logger.error("OpenAI streaming error: {e}", e=exc)
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
    ) -> tuple[str, list[str]]:
        use_responses = _uses_responses_api(self._model)
        tools_called: list[str] = []

        if use_responses:
            return await self._complete_with_tools_responses(
                system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )
        else:
            return await self._complete_with_tools_chat(
                system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )

    async def _complete_with_tools_responses(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str,
        image_urls: list[str] | None,
        user_id: str | None,
        tools_called: list[str],
    ) -> tuple[str, list[str]]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, True
            )
            full_messages[-1] = last_msg

        try:
            resp_tools = _tools_for_responses_api(tools)
            resp_kwargs: dict = {
                "model": self._model,
                "input": full_messages,
                "tools": resp_tools,
            }
            uses_reasoning = self._reasoning_effort and self._reasoning_effort != "none"
            if uses_reasoning:
                resp_kwargs["reasoning"] = {"effort": self._reasoning_effort}
            if self._max_tokens and not uses_reasoning:
                resp_kwargs["max_output_tokens"] = self._max_tokens
            response = await self._client.responses.create(**resp_kwargs)

            total_input = 0
            total_output = 0
            total_cached = 0

            if response.usage:
                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens
                try:
                    total_cached += response.usage.input_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    pass

            max_iterations = 3
            for _ in range(max_iterations):
                function_calls = [
                    item for item in response.output
                    if item.type == "function_call"
                ]
                if not function_calls:
                    break

                full_messages.extend(response.output)
                for fc in function_calls:
                    tools_called.append(fc.name)
                    result = await tool_executor(fc.name, fc.arguments)
                    full_messages.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": result,
                    })

                resp_kwargs["input"] = full_messages
                response = await self._client.responses.create(**resp_kwargs)
                if response.usage:
                    total_input += response.usage.input_tokens
                    total_output += response.usage.output_tokens
                    try:
                        total_cached += response.usage.input_tokens_details.cached_tokens or 0
                    except (AttributeError, TypeError):
                        pass

            text = response.output_text
            cost = estimate_cost(self._model, total_input, total_output, cached_input_tokens=total_cached)
            logger.info(
                "OpenAI {model} (Responses+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=self._model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
            )
            return text, tools_called

        except Exception as exc:
            logger.error("OpenAI Responses API (tools) error: {e}", e=exc)
            fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
            return fallback, tools_called

    async def _complete_with_tools_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str,
        image_urls: list[str] | None,
        user_id: str | None,
        tools_called: list[str],
    ) -> tuple[str, list[str]]:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, False
            )
            full_messages[-1] = last_msg

        total_input = 0
        total_output = 0
        total_cached = 0

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,
                    tools=tools,
                    temperature=self._temperature,
                    max_completion_tokens=self._max_tokens,
                )

                usage = response.usage
                total_input += usage.prompt_tokens
                total_output += usage.completion_tokens
                try:
                    total_cached += usage.prompt_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    pass

                msg = response.choices[0].message

                max_iterations = 3
                for _ in range(max_iterations):
                    if not msg.tool_calls:
                        break

                    full_messages.append(msg)
                    for tc in msg.tool_calls:
                        tools_called.append(tc.function.name)
                        result = await tool_executor(tc.function.name, tc.function.arguments)
                        full_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        tools=tools,
                        temperature=self._temperature,
                        max_completion_tokens=self._max_tokens,
                    )
                    usage = response.usage
                    total_input += usage.prompt_tokens
                    total_output += usage.completion_tokens
                    try:
                        total_cached += usage.prompt_tokens_details.cached_tokens or 0
                    except (AttributeError, TypeError):
                        pass
                    msg = response.choices[0].message

                cost = estimate_cost(self._model, total_input, total_output, cached_input_tokens=total_cached)
                logger.info(
                    "OpenAI {model} (Chat+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=self._model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
                )
                return msg.content.strip() if msg.content else FALLBACK_RESPONSE, tools_called

            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("Rate limited (tools), retrying in {w}s", w=wait)
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("OpenAI server error {code} (tools), retrying in {w}s", code=exc.status_code, w=wait)
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error {code} (tools): {e}", code=exc.status_code, e=exc)
                    break
            except Exception as exc:
                logger.error("OpenAI unexpected error (tools): {e}", e=exc)
                break

        fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
        return fallback, tools_called

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if _uses_responses_api(self._model):
            for attempt in range(3):
                try:
                    kwargs: dict = {
                        "model": self._model,
                        "input": full_messages,
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": schema_name,
                                "schema": schema,
                            }
                        },
                    }
                    if self._reasoning_effort and self._reasoning_effort != "none":
                        kwargs["reasoning"] = {"effort": self._reasoning_effort}

                    response = await self._client.responses.create(**kwargs)

                    if response.status != "completed":
                        raise RuntimeError(
                            f"Structured output truncated or incomplete "
                            f"(status={response.status!r})"
                        )

                    text = response.output_text
                    if not text:
                        for item in response.output:
                            if hasattr(item, "content"):
                                for block in item.content:
                                    t = getattr(block, "text", None)
                                    if t:
                                        text = t
                                        break
                            if text:
                                break
                    if not text:
                        output_types = [f"{item.type}" for item in response.output]
                        raise RuntimeError(
                            f"Structured output empty despite status=completed "
                            f"(output_types={output_types})"
                        )

                    parsed = json.loads(text)

                    if response.usage:
                        try:
                            cached = response.usage.input_tokens_details.cached_tokens or 0
                        except (AttributeError, TypeError):
                            cached = 0
                        cost = estimate_cost(
                            self._model, response.usage.input_tokens,
                            response.usage.output_tokens, cached_input_tokens=cached,
                        )
                        logger.info(
                            "OpenAI {model} (Responses/structured) — {inp}in/{out}out tokens, "
                            "${cost:.6f} [{purpose}]",
                            model=self._model, inp=response.usage.input_tokens,
                            out=response.usage.output_tokens, cost=cost, purpose=purpose,
                        )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e}",
                            code=exc.status_code, e=exc,
                        )
                        break
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/responses): {e}", e=exc)
                    break

            raise RuntimeError(
                f"complete_structured failed after 3 attempts (model={self._model!r})"
            )

        else:
            for attempt in range(3):
                try:
                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=full_messages,
                        temperature=self._temperature,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema_name,
                                "schema": schema,
                                "strict": True,
                            },
                        },
                    )

                    choice = response.choices[0]
                    if choice.finish_reason == "length":
                        raise RuntimeError(
                            "Structured output truncated (finish_reason='length')"
                        )

                    parsed = json.loads(choice.message.content)

                    usage = response.usage
                    try:
                        cached = usage.prompt_tokens_details.cached_tokens or 0
                    except (AttributeError, TypeError):
                        cached = 0
                    cost = estimate_cost(
                        self._model, usage.prompt_tokens, usage.completion_tokens,
                        cached_input_tokens=cached,
                    )
                    logger.info(
                        "OpenAI {model} (Chat/structured) — {inp}in/{out}out tokens, "
                        "${cost:.6f} [{purpose}]",
                        model=self._model, inp=usage.prompt_tokens,
                        out=usage.completion_tokens, cost=cost, purpose=purpose,
                    )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait, a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code, w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e}",
                            code=exc.status_code, e=exc,
                        )
                        break
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/chat): {e}", e=exc)
                    break

            raise RuntimeError(
                f"complete_structured failed after 3 attempts (model={self._model!r})"
            )

    # ── Image generation (OpenAI-specific, not part of BaseLLMClient) ─────────

    @staticmethod
    def estimate_image_cost(model: str, quality: str, size: str) -> float:
        model_costs = IMAGE_COSTS.get(model)
        if not model_costs:
            return 0.25
        cost = model_costs.get((quality, size))
        if cost is not None:
            return cost
        return max(model_costs.values())

    async def generate_image(self, prompt: str, config: "ImageGenerationConfig", sender_id: str | None = None) -> dict:
        model = config.model
        quality = config.quality
        size = config.size

        if config.daily_limit != -1:
            today_total = await self._db.get_total_image_count_today()
            if today_total >= config.daily_limit:
                raise ValueError("Limite quotidienne de génération d'images atteinte.")
        if config.per_user_limit != -1 and sender_id:
            user_today = await self._db.get_user_image_count_today(sender_id)
            if user_today >= config.per_user_limit:
                raise ValueError("Tu as atteint ta limite d'images pour aujourd'hui.")

        DATA_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

        last_error = None
        for attempt in range(3):
            try:
                response = await self._client.images.generate(
                    model=model,
                    prompt=prompt,
                    n=1,
                    size=size,
                    quality=quality,
                    background=config.background,
                    output_format=config.format if config.format in ("png", "jpeg", "webp") else "png",
                )
                break
            except RateLimitError as e:
                last_error = e
                logger.warning("Image rate limit, attempt {a}/3: {e}", a=attempt + 1, e=e)
                await asyncio.sleep(2 ** attempt)
            except APIStatusError as e:
                if e.status_code == 400:
                    body = getattr(e, "body", None) or {}
                    detail = body.get("error", {}).get("message", str(e)) if isinstance(body, dict) else str(e)
                    logger.warning("Image API 400: {detail}", detail=detail)
                    raise ValueError(f"Erreur API image : {detail}") from e
                if e.status_code >= 500:
                    last_error = e
                    logger.warning("Image API 5xx, attempt {a}/3: {e}", a=attempt + 1, e=e)
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        else:
            logger.error("Image generation failed after 3 attempts: {e}", e=last_error)
            raise RuntimeError("Échec de la génération d'image après 3 tentatives.")

        image_data = base64.b64decode(response.data[0].b64_json)
        file_ext = config.format if config.format in ("png", "jpeg", "webp") else "png"
        file_id = str(uuid.uuid4())
        file_name = f"{file_id}.{file_ext}"
        file_path = DATA_GALLERY_DIR / file_name
        file_path.write_bytes(image_data)

        cost_usd = self.estimate_image_cost(model, quality, size)

        revised = getattr(response.data[0], "revised_prompt", None)

        return {
            "file_id": file_id,
            "file_name": file_name,
            "file_path": str(file_path),
            "cost_usd": cost_usd,
            "revised_prompt": revised,
            "model": model,
            "quality": quality,
            "size": size,
        }

    async def get_daily_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400)

    async def get_monthly_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400 * 30)
