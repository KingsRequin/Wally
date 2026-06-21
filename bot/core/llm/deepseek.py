# bot/core/llm/deepseek.py
from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from loguru import logger
from openai import AsyncOpenAI

from bot.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE


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
            await self._db.log_cost(
                model=response.model or self._model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cost_usd=0.0,
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

            for tc in msg.tool_calls:
                tools_called.append(tc.function.name)
                args = self._safe_parse_args(tc.function.arguments)
                try:
                    result = await tool_executor(tc.function.name, json.dumps(args))
                except Exception as e:
                    result = f"Tool error: {e}"
                    logger.warning("Tool executor error for {name}: {e}", name=tc.function.name, e=e)
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
        try:
            response = await self._client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}] + messages,
                tools=[tool_def],
                tool_choice={"type": "function", "function": {"name": schema_name}},
                **params,
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                raise RuntimeError(f"DeepSeek complete_structured: pas de tool_call dans la réponse")
            raw_args = msg.tool_calls[0].function.arguments
            result = self._safe_parse_args(raw_args)
            if not result:
                raise RuntimeError(f"DeepSeek complete_structured: JSON vide après repair")
            await self._log_cost(response, purpose, user_id)
            return result
        except Exception as e:
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
                **params,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
        except Exception as e:
            logger.error("DeepSeek complete_stream() failed: {e}", e=e)
            yield FALLBACK_RESPONSE
