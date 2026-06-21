# bot/core/llm/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Awaitable, Callable, Optional


FALLBACK_RESPONSE = (
    "Je rencontre un problème technique, réessaie dans un moment. \U0001f527"
)

FALLBACK_IMAGE_RESPONSE = "Désolé, j'ai une poussière dans l'œil… j'arrive pas à la voir \U0001f441\ufe0f"


class BaseLLMClient(ABC):
    """Abstract base class for LLM providers.

    All LLM clients (OpenAI, Claude, etc.) must implement these methods.
    Tools are always passed in OpenAI Chat Completions format (canonical):
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Each provider converts internally to its own format.

    Messages use the OpenAI format:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    Each provider converts internally (e.g. Claude separates system from messages).
    """

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        purpose: str = "response",
        image_urls: list[str] | None = None,
        user_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a text completion.

        Returns the model's text response, or FALLBACK_RESPONSE on total failure.
        """

    @abstractmethod
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
        """Generate a completion with function calling support.

        tools: list of tool definitions in OpenAI Chat Completions format.
        tool_executor: async callback (function_name, arguments_json) -> result_string.

        Returns (response_text, list_of_tool_names_called).
        Never raises — returns (FALLBACK_RESPONSE, [...]) on total failure.
        """

    @abstractmethod
    async def complete_structured(
        self,
        system_prompt: str,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        purpose: str = "structured",
        user_id: str | None = None,
    ) -> dict:
        """Generate a structured JSON output conforming to the given schema.

        Raises RuntimeError on truncation or total failure.
        """

    @abstractmethod
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
        """Stream a text completion as an async generator of text chunks.

        Yields text deltas as they arrive. When tools are provided and the model
        requests tool calls, executes them via tool_executor and streams the
        final response. Implementations without tool streaming support fall back
        to complete_with_tools() and yield the result as a single chunk.
        On error, yields FALLBACK_RESPONSE as a single chunk and stops.
        """
