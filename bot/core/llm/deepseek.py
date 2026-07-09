# bot/core/llm/deepseek.py
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE


# Coût DeepSeek par 1M tokens : (input cache hit, input cache miss, output) en USD.
# Source : https://api-docs.deepseek.com/quick_start/pricing/ (vérifié 2026-06-24).
# deepseek-chat / deepseek-reasoner = alias de flash, dépréciés le 2026-07-24.
_DEEPSEEK_COSTS: dict[str, tuple[float, float, float]] = {
    "deepseek-v4-pro": (0.003625, 0.435, 0.87),
    "deepseek-v4-flash": (0.0028, 0.14, 0.28),
    "deepseek-chat": (0.0028, 0.14, 0.28),
    "deepseek-reasoner": (0.0028, 0.14, 0.28),
}
_DEEPSEEK_FALLBACK_COST = (0.0028, 0.14, 0.28)

# Peak-valley DeepSeek : avec la sortie officielle de V4 (mi-juillet 2026), le
# tarif passe ×2 pendant les heures de pointe UTC (surtaxe uniforme sur hit/miss/
# output). Source : email DeepSeek 2026-06-29.
# `_DEEPSEEK_PEAK_START` = date UTC d'activation ; laissée à None tant que la
# bascule n'est pas confirmée (DeepSeek envoie un préavis 24h avant). Tant qu'elle
# vaut None, le calcul reste au tarif normal — zéro changement de comportement.
_DEEPSEEK_PEAK_START: date | None = None
_DEEPSEEK_PEAK_MULTIPLIER = 2.0


def _is_deepseek_peak(now: datetime | None = None) -> bool:
    """True si `now` (UTC) tombe dans une plage de pointe DeepSeek (tarif ×2).

    Plages UTC : 01:00–04:00 et 06:00–10:00 (04:00–06:00 = creux). Inactif tant
    que `_DEEPSEEK_PEAK_START` est None ou que la date d'activation n'est pas
    atteinte. `now` est injectable pour les tests.
    """
    if _DEEPSEEK_PEAK_START is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.date() < _DEEPSEEK_PEAK_START:
        return False
    h = now.hour
    return (1 <= h < 4) or (6 <= h < 10)


def _deepseek_cost(model: str, usage: Any, now: datetime | None = None) -> float:
    """Coût USD d'un appel depuis l'`usage` retourné par l'API DeepSeek.

    DeepSeek expose `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`
    (leur somme = `prompt_tokens`). Si absents (vieux modèle, mock), tout est
    facturé au tarif cache miss. Le matching modèle privilégie le préfixe le
    plus long (ex. `deepseek-v4-pro-2026...` → `deepseek-v4-pro`).

    Le tarif de pointe (×2) s'applique si `_is_deepseek_peak(now)` — inactif par
    défaut (voir `_DEEPSEEK_PEAK_START`).
    """
    rates = _DEEPSEEK_COSTS.get(model) or next(
        (v for k, v in sorted(_DEEPSEEK_COSTS.items(), key=lambda x: len(x[0]), reverse=True)
         if model.startswith(k)),
        _DEEPSEEK_FALLBACK_COST,
    )
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    hit = getattr(usage, "prompt_cache_hit_tokens", None)
    miss = getattr(usage, "prompt_cache_miss_tokens", None)
    if hit is None or miss is None:
        hit, miss = 0, prompt_tokens
    completion = getattr(usage, "completion_tokens", 0) or 0
    cost = (hit * rates[0] + miss * rates[1] + completion * rates[2]) / 1_000_000
    if _is_deepseek_peak(now):
        cost *= _DEEPSEEK_PEAK_MULTIPLIER
    return cost


class DeepSeekLLMClient(BaseLLMClient):
    """Client DeepSeek V4 via OpenAI-compatible API.

    Gère :
    - thinking mode (disabled/enabled) via extra_body
    - preservation de reasoning_content uniquement sur les turns avec tool_calls
    - JSON repair pour les arguments malformés
    - cap max_tool_iters sur les boucles tool calling
    - complete_structured via forced tool_choice
    """

    def __init__(
        self,
        model: str,
        db: Any,
        temperature: float = 1.0,
        max_tokens: int = 2048,
        thinking_type: str = "disabled",   # "disabled" | "enabled"
        thinking_effort: str = "low",       # "low" | "high" | "max"
        max_tool_iters: int = 6,
    ) -> None:
        self._model = model
        self._db = db
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_type = thinking_type
        self._thinking_effort = thinking_effort
        self._max_tool_iters = max_tool_iters
        self._client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _extra_body(self, thinking_override: str | None = None) -> dict:
        t = thinking_override or self._thinking_type
        if t == "enabled":
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": self._thinking_effort,
            }
        return {"thinking": {"type": "disabled"}}

    def _api_params(self, thinking_override: str | None = None, max_tokens: int | None = None) -> dict:
        """Construit les kwargs communs pour chat.completions.create."""
        extra = self._extra_body(thinking_override)
        thinking_active = extra.get("thinking", {}).get("type") == "enabled"
        params: dict = {
            "model": self._model,
            "max_tokens": max_tokens or self._max_tokens,
            "extra_body": extra,
        }
        if not thinking_active:
            params["temperature"] = self._temperature
        return params

    @staticmethod
    def _safe_parse_args(raw: str) -> dict:
        """Parse les arguments JSON d'un tool call avec réparation si malformé."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            for suffix in ['"', '"}', '"}}', '}']:
                try:
                    return json.loads(raw + suffix)
                except json.JSONDecodeError:
                    continue
            logger.warning("DeepSeek: impossible de réparer le JSON d'arguments: {raw!r}", raw=raw[:100])
            return {}

    async def _log_cost(self, response: Any, purpose: str, user_id: str | None) -> None:
        try:
            usage = response.usage
            model = response.model or self._model
            await self._db.log_cost(
                model=model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cost_usd=_deepseek_cost(model, usage),
                purpose=purpose,
                user_id=user_id,
            )
        except Exception as e:
            logger.debug("DeepSeek log_cost failed (non-fatal): {e}", e=e)

    # ── Interface publique ────────────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **self._api_params(max_tokens=max_tokens),
            )
            text = response.choices[0].message.content or ""
            await self._log_cost(response, purpose, user_id)
            return text
        except Exception as e:
            logger.error("DeepSeek complete() failed: {e}", e=e)
            return FALLBACK_RESPONSE

    async def complete_with_reasoning(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "reasoning",
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, str]:
        """Un appel avec le mode *thinking* forcé. Retourne (content, reasoning).

        - `reasoning` = `reasoning_content` exposé par DeepSeek = la pensée privée
          (le `<think>`), jamais montrée telle quelle à l'utilisateur.
        - `content` = la sortie publique (ici : la décision en tags d'action).
        Si le serveur ne renvoie pas de reasoning, `reasoning` vaut "".
        Fondation du reasoning unifié (un seul appel pense + décide).
        """
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                **self._api_params(thinking_override="enabled", max_tokens=max_tokens),
            )
            msg = response.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            await self._log_cost(response, purpose, user_id)
            return content, reasoning
        except Exception as e:
            logger.error("DeepSeek complete_with_reasoning() failed: {e}", e=e)
            return "", ""

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
        history = list(messages)
        tools_called: list[str] = []
        params = self._api_params()

        for iteration in range(self._max_tool_iters):
            try:
                response = await self._client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}] + history,
                    tools=tools,
                    **params,
                )
            except Exception as e:
                logger.error("DeepSeek complete_with_tools() iter {i} failed: {e}", i=iteration, e=e)
                return (FALLBACK_RESPONSE, tools_called)

            msg = response.choices[0].message

            if not msg.tool_calls:
                # Pas de tool call → NE PAS inclure reasoning_content (règle DeepSeek)
                text = msg.content or ""
                await self._log_cost(response, purpose, user_id)
                return (text, tools_called)

            # Tool call → reasoning_content DOIT être préservé
            assistant_entry: dict = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                assistant_entry["reasoning_content"] = reasoning
            history.append(assistant_entry)

            # Les tool_calls d'un même tour sont indépendants → exécution en parallèle.
            # (ex. plusieurs web_search enchaînés : 4×4s séquentiel → ~4s en parallèle)
            async def _run_tool(tc):
                args = self._safe_parse_args(tc.function.arguments)
                try:
                    return await tool_executor(tc.function.name, json.dumps(args))
                except Exception as e:
                    logger.warning("Tool executor error for {name}: {e}", name=tc.function.name, e=e)
                    return f"Tool error: {e}"

            for tc in msg.tool_calls:
                tools_called.append(tc.function.name)
            results = await asyncio.gather(*(_run_tool(tc) for tc in msg.tool_calls))
            for tc, result in zip(msg.tool_calls, results):
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # Cap atteint → génère une réponse finale sans tools
        logger.warning("DeepSeek: max_tool_iters={n} atteint, génération finale sans tools", n=self._max_tool_iters)
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + history,
                **params,
            )
            text = response.choices[0].message.content or FALLBACK_RESPONSE
            await self._log_cost(response, purpose, user_id)
            return (text, tools_called)
        except Exception as e:
            logger.error("DeepSeek complete_with_tools() final fallback failed: {e}", e=e)
            return (FALLBACK_RESPONSE, tools_called)

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        """Force un tool_choice pour obtenir du JSON structuré conforme au schema."""
        tool_def = {
            "type": "function",
            "function": {
                "name": schema_name,
                "description": f"Retourne une réponse structurée {schema_name}",
                "parameters": schema,
            },
        }
        # Thinking désactivé pour le structured output (incompatible + inutile)
        params = self._api_params(thinking_override="disabled")
        # « pas de tool_call » / « JSON vide après repair » sont souvent transitoires
        # (non-déterminisme du LLM) → un réessai immédiat évite la majorité des échecs.
        for attempt in range(2):
            try:
                response = await self._client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}] + messages,
                    tools=[tool_def],
                    tool_choice={"type": "function", "function": {"name": schema_name}},
                    **params,
                )
                msg = response.choices[0].message
                if not msg.tool_calls:
                    raise RuntimeError("DeepSeek complete_structured: pas de tool_call dans la réponse")
                raw_args = msg.tool_calls[0].function.arguments
                result = self._safe_parse_args(raw_args)
                if not result:
                    raise RuntimeError("DeepSeek complete_structured: JSON vide après repair")
                await self._log_cost(response, purpose, user_id)
                return result
            except Exception as e:
                if attempt == 0:
                    logger.warning("DeepSeek complete_structured() échec, réessai: {e}", e=e)
                    continue
                logger.error("DeepSeek complete_structured() failed: {e}", e=e)
                raise RuntimeError(f"DeepSeek structured output failed: {e}") from e

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        tools: list[dict] | None = None,
        tool_executor: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming via SSE DeepSeek. Fallback non-streamé si tools présents."""
        if tools and tool_executor:
            # Pas de streaming avec tools — fallback sur complete_with_tools
            text, _ = await self.complete_with_tools(
                system_prompt, messages, tools, tool_executor,
                purpose=purpose, user_id=user_id,
            )
            yield text
            return

        try:
            params = self._api_params()
            async with self._client.chat.completions.stream(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                stream_options={"include_usage": True},
                **params,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                # Log du coût après épuisement du flux : l'usage (tokens + cache)
                # n'arrive que dans le chunk final via stream_options.include_usage.
                # Isolé : une erreur ici ne doit jamais injecter le fallback.
                try:
                    await self._log_cost(await stream.get_final_completion(), purpose, user_id)
                except Exception as e:
                    logger.debug("DeepSeek stream cost log failed (non-fatal): {e}", e=e)
        except Exception as e:
            logger.error("DeepSeek complete_stream() failed: {e}", e=e)
            yield FALLBACK_RESPONSE
