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

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        model: Optional[str] = None,
        purpose: str = "response",
    ) -> str:
        model = model or self._config.openai.primary_model
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=self._config.openai.temperature,
                    max_tokens=self._config.openai.max_tokens,
                )
                usage = response.usage
                cost = estimate_cost(model, usage.prompt_tokens, usage.completion_tokens)
                await self._db.log_cost(
                    model, usage.prompt_tokens, usage.completion_tokens, cost, purpose
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

        return FALLBACK_RESPONSE

    async def complete_secondary(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "summary",
    ) -> str:
        return await self.complete(
            system_prompt,
            messages,
            model=self._config.openai.secondary_model,
            purpose=purpose,
        )

    async def get_daily_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400)

    async def get_monthly_cost(self) -> float:
        return await self._db.get_cost_since(time.time() - 86_400 * 30)
