# bot/core/openai_client.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

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
    "gpt-4o": (5.0, 15.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "o1": (15.0, 60.0),
    "o1-mini": (3.0, 12.0),
    "o3-mini": (1.10, 4.40),
    "chatgpt-4o-latest": (5.0, 15.0),
}

FALLBACK_COST = (5.0, 15.0)  # default if model unknown

FALLBACK_RESPONSE = (
    "Je rencontre un problème technique, réessaie dans un moment. 🔧"
)

FALLBACK_IMAGE_RESPONSE = "Désolé, j'ai une poussière dans l'œil… j'arrive pas à la voir 👁️"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    # Exact match first, then longest-prefix match to avoid "gpt-4o" matching "gpt-4o-mini"
    costs = MODEL_COSTS.get(model) or next(
        (v for k, v in sorted(MODEL_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        FALLBACK_COST,
    )
    return (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000


class OpenAIClient:
    def __init__(self, config: "Config", db: "Database"):
        self._config = config
        self._db = db
        api_key = os.environ.get("OPENAI_API_KEY", "dummy-key-for-testing")
        self._client = AsyncOpenAI(api_key=api_key)

    async def _complete_responses_api(
        self, model: str, messages: list[dict], purpose: str, user_id: str | None = None
    ) -> str:
        response = await self._client.responses.create(
            model=model,
            input=messages,
            reasoning={"effort": "low"},
        )
        text = response.output_text
        if response.usage:
            cost = estimate_cost(
                model, response.usage.input_tokens, response.usage.output_tokens
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
    ) -> str:
        model = model or self._config.openai.primary_model
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        if image_urls:
            last_msg = dict(full_messages[-1])
            last_msg["content"] = self._build_image_content(
                last_msg["content"], image_urls, _uses_responses_api(model)
            )
            full_messages[-1] = last_msg

        if _uses_responses_api(model):
            try:
                return await self._complete_responses_api(model, full_messages, purpose, user_id=user_id)
            except Exception as exc:
                logger.error("OpenAI Responses API error: {e}", e=exc)
                return FALLBACK_IMAGE_RESPONSE if image_urls else FALLBACK_RESPONSE

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=self._config.openai.temperature,
                    max_completion_tokens=self._config.openai.max_tokens,
                )
                usage = response.usage
                cost = estimate_cost(model, usage.prompt_tokens, usage.completion_tokens)
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

    async def get_daily_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400)

    async def get_monthly_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400 * 30)
