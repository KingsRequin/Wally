# bot/core/openai_client.py
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

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database

_RESPONSES_API_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _uses_responses_api(model: str) -> bool:
    return any(model.startswith(p) for p in _RESPONSES_API_PREFIXES)


# Cost per 1M tokens (input, output) in USD — approximate
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

FALLBACK_COST = (5.0, 15.0)  # default if model unknown

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

FALLBACK_RESPONSE = (
    "Je rencontre un problème technique, réessaie dans un moment. 🔧"
)


def _tools_for_responses_api(tools: list[dict]) -> list[dict]:
    """Convert Chat Completions tool format to Responses API format.

    Chat Completions: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Responses API:    {"type": "function", "name": ..., "description": ..., "parameters": ...}
    """
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

FALLBACK_IMAGE_RESPONSE = "Désolé, j'ai une poussière dans l'œil… j'arrive pas à la voir 👁️"


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    # Exact match first, then longest-prefix match to avoid "gpt-4o" matching "gpt-4o-mini"
    costs = MODEL_COSTS.get(model) or next(
        (v for k, v in sorted(MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        FALLBACK_COST,
    )
    # Cached input tokens are billed at 50% of the normal input rate
    non_cached = input_tokens - cached_input_tokens
    return (
        non_cached * costs[0]
        + cached_input_tokens * costs[0] * 0.5
        + output_tokens * costs[1]
    ) / 1_000_000


class OpenAIClient:
    def __init__(self, config: "Config", db: "Database"):
        self._config = config
        self._db = db
        api_key = os.environ.get("OPENAI_API_KEY", "dummy-key-for-testing")
        self._client = AsyncOpenAI(api_key=api_key)

    async def _complete_responses_api(
        self, model: str, messages: list[dict], purpose: str,
        user_id: str | None = None, max_tokens: int | None = None,
    ) -> str:
        kwargs: dict = {
            "model": model,
            "input": messages,
        }
        effort = self._config.openai.reasoning_effort
        if effort and effort != "none":
            kwargs["reasoning"] = {"effort": effort}
        verbosity = self._config.openai.text_verbosity
        if verbosity:
            kwargs["text"] = {"format": {"type": "text"}, "verbosity": verbosity}
        effective_max = max_tokens or self._config.openai.max_tokens
        if effective_max:
            kwargs["max_output_tokens"] = effective_max
        response = await self._client.responses.create(**kwargs)
        text = response.output_text
        if response.usage:
            try:
                cached = response.usage.input_tokens_details.cached_tokens or 0
            except (AttributeError, TypeError):
                cached = 0
            cost = estimate_cost(
                model, response.usage.input_tokens, response.usage.output_tokens,
                cached_input_tokens=cached,
            )
            await self._db.log_cost(
                model,
                response.usage.input_tokens,
                response.usage.output_tokens,
                cost,
                purpose,
                user_id=user_id,
            )
            logger.info(
                "OpenAI {model} (Responses) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=model,
                inp=response.usage.input_tokens,
                out=response.usage.output_tokens,
                cost=cost,
                purpose=purpose,
            )
        return text

    def _build_image_content(
        self, text: str, image_urls: list[str], use_responses_api: bool
    ) -> list[dict]:
        """Build image content blocks for the last message.

        Callers must ensure text is non-empty; image-only messages should be
        prefixed with descriptive text (e.g. "Regarde cette image.") at the
        handler level to avoid empty text content blocks.
        """
        if use_responses_api:
            content = [{"type": "input_text", "text": text}]
            for url in image_urls:
                content.append({"type": "input_image", "image_url": url})
        else:
            content = [{"type": "text", "text": text}]
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return content

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        model: Optional[str] = None,
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        model = model or self._config.openai.primary_model
        effective_max_tokens = max_tokens or self._config.openai.max_tokens
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, _uses_responses_api(model)
            )
            full_messages[-1] = last_msg

        if _uses_responses_api(model):
            try:
                return await self._complete_responses_api(model, full_messages, purpose, user_id=user_id, max_tokens=effective_max_tokens)
            except Exception as exc:
                logger.error("OpenAI Responses API error: {e}", e=exc)
                return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=self._config.openai.temperature,
                    max_completion_tokens=effective_max_tokens,
                )
                usage = response.usage
                try:
                    cached = usage.prompt_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    cached = 0
                cost = estimate_cost(
                    model, usage.prompt_tokens, usage.completion_tokens,
                    cached_input_tokens=cached,
                )
                await self._db.log_cost(
                    model, usage.prompt_tokens, usage.completion_tokens, cost, purpose,
                    user_id=user_id,
                )
                logger.info(
                    "OpenAI {model} — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=model,
                    inp=usage.prompt_tokens,
                    out=usage.completion_tokens,
                    cost=cost,
                    purpose=purpose,
                )
                return response.choices[0].message.content.strip()

            except RateLimitError:
                wait = 2**attempt
                logger.warning(
                    "Rate limited by OpenAI, retrying in {w}s (attempt {a}/3)",
                    w=wait,
                    a=attempt + 1,
                )
                await asyncio.sleep(wait)

            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2**attempt
                    logger.warning(
                        "OpenAI server error {code}, retrying in {w}s",
                        code=exc.status_code,
                        w=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI API error {code}: {e}", code=exc.status_code, e=exc)
                    break

            except Exception as exc:
                logger.error("OpenAI unexpected error: {e}", e=exc)
                break

        return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        model: Optional[str] = None,
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
    ) -> tuple[str, list[str]]:
        """Complete with function calling support.

        Returns (response_text, list_of_tool_names_called).
        tool_executor receives (function_name, arguments_json) and returns the result string.
        """
        model = model or self._config.openai.primary_model
        use_responses = _uses_responses_api(model)
        tools_called: list[str] = []

        if use_responses:
            return await self._complete_with_tools_responses(
                model, system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )
        else:
            return await self._complete_with_tools_chat(
                model, system_prompt, messages, tools, tool_executor,
                purpose, image_urls, user_id, tools_called,
            )

    async def _complete_with_tools_responses(
        self,
        model: str,
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
                "model": model,
                "input": full_messages,
                "tools": resp_tools,
            }
            effort = self._config.openai.reasoning_effort
            if effort and effort != "none":
                resp_kwargs["reasoning"] = {"effort": effort}
            if self._config.openai.max_tokens:
                resp_kwargs["max_output_tokens"] = self._config.openai.max_tokens
            response = await self._client.responses.create(**resp_kwargs)

            # Track total usage across iterations
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

            # Check for function calls in output
            max_iterations = 3
            for _ in range(max_iterations):
                function_calls = [
                    item for item in response.output
                    if item.type == "function_call"
                ]
                if not function_calls:
                    break

                # Execute each tool call
                for fc in function_calls:
                    tools_called.append(fc.name)
                    result = await tool_executor(fc.name, fc.arguments)
                    full_messages.extend(response.output)
                    full_messages.append({
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": result,
                    })

                # Send results back
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
            cost = estimate_cost(model, total_input, total_output, cached_input_tokens=total_cached)
            await self._db.log_cost(model, total_input, total_output, cost, purpose, user_id=user_id)
            logger.info(
                "OpenAI {model} (Responses+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                model=model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
            )
            return text, tools_called

        except Exception as exc:
            logger.error("OpenAI Responses API (tools) error: {e}", e=exc)
            fallback = FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE
            return fallback, tools_called

    async def _complete_with_tools_chat(
        self,
        model: str,
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
                    model=model,
                    messages=full_messages,
                    tools=tools,
                    temperature=self._config.openai.temperature,
                    max_completion_tokens=self._config.openai.max_tokens,
                )

                usage = response.usage
                total_input += usage.prompt_tokens
                total_output += usage.completion_tokens
                try:
                    total_cached += usage.prompt_tokens_details.cached_tokens or 0
                except (AttributeError, TypeError):
                    pass

                msg = response.choices[0].message

                # Tool call loop
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
                        model=model,
                        messages=full_messages,
                        tools=tools,
                        temperature=self._config.openai.temperature,
                        max_completion_tokens=self._config.openai.max_tokens,
                    )
                    usage = response.usage
                    total_input += usage.prompt_tokens
                    total_output += usage.completion_tokens
                    try:
                        total_cached += usage.prompt_tokens_details.cached_tokens or 0
                    except (AttributeError, TypeError):
                        pass
                    msg = response.choices[0].message

                cost = estimate_cost(model, total_input, total_output, cached_input_tokens=total_cached)
                await self._db.log_cost(model, total_input, total_output, cost, purpose, user_id=user_id)
                logger.info(
                    "OpenAI {model} (Chat+tools) — {inp}in/{out}out tokens, ${cost:.6f} [{purpose}]",
                    model=model, inp=total_input, out=total_output, cost=cost, purpose=purpose,
                )
                return msg.content.strip() if msg.content else FALLBACK_RESPONSE, tools_called

            except RateLimitError:
                wait = 2**attempt
                logger.warning("Rate limited (tools), retrying in {w}s", w=wait)
                await asyncio.sleep(wait)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = 2**attempt
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

    async def complete_secondary(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "summary",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
    ) -> str:
        return await self.complete(
            system_prompt,
            messages,
            model=self._config.openai.secondary_model,
            purpose=purpose,
            image_urls=image_urls,
            user_id=user_id,
        )

    async def complete_secondary_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        """Call the secondary model with JSON schema structured output.

        Returns the parsed dict. Raises RuntimeError on truncation or total failure.
        Uses Responses API for o1/o3/o4/gpt-5 models, Chat Completions otherwise.
        """
        model = self._config.openai.secondary_model
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if _uses_responses_api(model):
            # Responses API path
            for attempt in range(3):
                try:
                    kwargs: dict = {
                        "model": model,
                        "input": full_messages,
                        "text": {
                            "format": {
                                "type": "json_schema",
                                "name": schema_name,
                                "schema": schema,
                            }
                        },
                    }
                    effort = self._config.openai.reasoning_effort
                    if effort and effort != "none":
                        kwargs["reasoning"] = {"effort": effort}
                    # NOTE: max_output_tokens intentionnellement omis pour les
                    # appels structured output — les schémas sont petits et bornés,
                    # et la limite inclut les tokens de raisonnement, ce qui
                    # provoque des troncatures (status='incomplete').

                    response = await self._client.responses.create(**kwargs)

                    if response.status != "completed":
                        raise RuntimeError(
                            f"Structured output truncated or incomplete "
                            f"(status={response.status!r})"
                        )

                    text = response.output_text
                    if not text:
                        # output_text vide malgré status=completed — extraire
                        # le JSON depuis les output items bruts (fallback)
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
                        output_types = [
                            f"{item.type}" for item in response.output
                        ]
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
                            model,
                            response.usage.input_tokens,
                            response.usage.output_tokens,
                            cached_input_tokens=cached,
                        )
                        await self._db.log_cost(
                            model,
                            response.usage.input_tokens,
                            response.usage.output_tokens,
                            cost,
                            purpose,
                            user_id=user_id,
                        )
                        logger.info(
                            "OpenAI {model} (Responses/structured) — {inp}in/{out}out tokens, "
                            "${cost:.6f} [{purpose}]",
                            model=model,
                            inp=response.usage.input_tokens,
                            out=response.usage.output_tokens,
                            cost=cost,
                            purpose=purpose,
                        )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait,
                        a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code,
                            w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e}",
                            code=exc.status_code,
                            e=exc,
                        )
                        break
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/responses): {e}", e=exc)
                    break

            raise RuntimeError(
                f"complete_secondary_structured failed after 3 attempts (model={model!r})"
            )

        else:
            # Chat Completions path
            for attempt in range(3):
                try:
                    response = await self._client.chat.completions.create(
                        model=model,
                        messages=full_messages,
                        temperature=self._config.openai.temperature,
                        # max_completion_tokens omis — même raison que Responses API
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
                        model,
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        cached_input_tokens=cached,
                    )
                    await self._db.log_cost(
                        model,
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        cost,
                        purpose,
                        user_id=user_id,
                    )
                    logger.info(
                        "OpenAI {model} (Chat/structured) — {inp}in/{out}out tokens, "
                        "${cost:.6f} [{purpose}]",
                        model=model,
                        inp=usage.prompt_tokens,
                        out=usage.completion_tokens,
                        cost=cost,
                        purpose=purpose,
                    )

                    return parsed

                except RuntimeError:
                    raise
                except RateLimitError:
                    wait = 2 ** attempt
                    logger.warning(
                        "Rate limited by OpenAI (structured), retrying in {w}s (attempt {a}/3)",
                        w=wait,
                        a=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                except APIStatusError as exc:
                    if exc.status_code >= 500:
                        wait = 2 ** attempt
                        logger.warning(
                            "OpenAI server error {code} (structured), retrying in {w}s",
                            code=exc.status_code,
                            w=wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "OpenAI API error {code} (structured): {e}",
                            code=exc.status_code,
                            e=exc,
                        )
                        break
                except Exception as exc:
                    logger.error("OpenAI unexpected error (structured/chat): {e}", e=exc)
                    break

            raise RuntimeError(
                f"complete_secondary_structured failed after 3 attempts (model={model!r})"
            )

    @staticmethod
    def estimate_image_cost(model: str, quality: str, size: str) -> float:
        model_costs = IMAGE_COSTS.get(model)
        if not model_costs:
            return 0.25
        cost = model_costs.get((quality, size))
        if cost is not None:
            return cost
        return max(model_costs.values())

    async def generate_image(self, prompt: str, sender_id: str | None = None) -> dict:
        cfg = self._config.image_generation
        model = cfg.model
        quality = cfg.quality
        size = cfg.size

        # Check limits
        if cfg.daily_limit != -1:
            today_total = await self._db.get_total_image_count_today()
            if today_total >= cfg.daily_limit:
                raise ValueError("Limite quotidienne de génération d'images atteinte.")
        if cfg.per_user_limit != -1 and sender_id:
            user_today = await self._db.get_user_image_count_today(sender_id)
            if user_today >= cfg.per_user_limit:
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
                    background=cfg.background,
                    response_format="b64_json",
                )
                break
            except RateLimitError as e:
                last_error = e
                logger.warning("Image rate limit, attempt {a}/3: {e}", a=attempt + 1, e=e)
                await asyncio.sleep(2 ** attempt)
            except APIStatusError as e:
                if e.status_code == 400:
                    raise ValueError("Prompt refusé par la modération OpenAI.") from e
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
        file_ext = cfg.format if cfg.format in ("png", "jpeg", "webp") else "png"
        file_id = str(uuid.uuid4())
        file_name = f"{file_id}.{file_ext}"
        file_path = DATA_GALLERY_DIR / file_name
        file_path.write_bytes(image_data)

        cost_usd = self.estimate_image_cost(model, quality, size)
        await self._db.log_cost(model, 0, 0, cost_usd, purpose="image_generation", user_id=sender_id)

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
