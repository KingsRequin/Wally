# wally_v2/core/llm/fallback.py
from __future__ import annotations

from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from loguru import logger

from wally_v2.core.llm.base import BaseLLMClient, FALLBACK_RESPONSE


class FallbackLLMClient(BaseLLMClient):
    """Wrappe deux clients LLM : essaie le primaire, bascule sur le secours en cas d'échec.

    Un échec = exception levée OU retour de FALLBACK_RESPONSE (les clients
    concrets attrapent leurs propres exceptions et renvoient ce sentinel).
    """

    def __init__(self, primary: BaseLLMClient, fallback: BaseLLMClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
        trace: Any = None,
    ) -> str:
        try:
            result = await self._primary.complete(
                system_prompt, messages, purpose=purpose, image_urls=image_urls,
                user_id=user_id, max_tokens=max_tokens, trace=trace,
            )
            if result and result != FALLBACK_RESPONSE:
                return result
            logger.warning("FallbackLLM: primaire a renvoyé FALLBACK, bascule sur secours")
        except Exception as e:
            logger.warning("FallbackLLM: primaire a levé {}, bascule sur secours", e)
        return await self._fallback.complete(
            system_prompt, messages, purpose=purpose, image_urls=image_urls,
            user_id=user_id, max_tokens=max_tokens, trace=trace,
        )

    async def complete_with_tools(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, str], Awaitable[str]],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace: Any = None,
    ) -> tuple[str, list[str]]:
        try:
            text, called = await self._primary.complete_with_tools(
                system_prompt, messages, tools, tool_executor, purpose=purpose,
                image_urls=image_urls, user_id=user_id, trace=trace,
            )
            if text and text != FALLBACK_RESPONSE:
                return (text, called)
            logger.warning("FallbackLLM: primaire (tools) a renvoyé FALLBACK, bascule sur secours")
        except Exception as e:
            logger.warning("FallbackLLM: primaire (tools) a levé {}, bascule sur secours", e)
        return await self._fallback.complete_with_tools(
            system_prompt, messages, tools, tool_executor, purpose=purpose,
            image_urls=image_urls, user_id=user_id, trace=trace,
        )

    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
        trace: Any = None,
    ) -> dict:
        try:
            return await self._primary.complete_structured(
                system_prompt, messages, schema, schema_name=schema_name,
                purpose=purpose, user_id=user_id, trace=trace,
            )
        except Exception as e:
            logger.warning("FallbackLLM: primaire (structured) a levé {}, bascule sur secours", e)
            return await self._fallback.complete_structured(
                system_prompt, messages, schema, schema_name=schema_name,
                purpose=purpose, user_id=user_id, trace=trace,
            )

    async def complete_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        trace: Any = None,
        tools: list[dict] | None = None,
        tool_executor: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ) -> AsyncGenerator[str, None]:
        # Buffer le premier chunk : s'il révèle une panne (vide ou FALLBACK),
        # on bascule sur le secours avant d'avoir streamé quoi que ce soit.
        try:
            agen = self._primary.complete_stream(
                system_prompt, messages, purpose=purpose, image_urls=image_urls,
                user_id=user_id, trace=trace, tools=tools, tool_executor=tool_executor,
            )
            first = None
            async for chunk in agen:
                first = chunk
                break
            if first is None or first == FALLBACK_RESPONSE:
                raise RuntimeError("primaire stream a renvoyé FALLBACK")
            yield first
            async for chunk in agen:
                yield chunk
            return
        except Exception as e:
            logger.warning("FallbackLLM: primaire (stream) en échec {}, bascule sur secours", e)
        async for chunk in self._fallback.complete_stream(
            system_prompt, messages, purpose=purpose, image_urls=image_urls,
            user_id=user_id, trace=trace, tools=tools, tool_executor=tool_executor,
        ):
            yield chunk
