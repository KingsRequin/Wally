# bot/core/web_search.py
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database


IMAGE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "image_search",
        "description": (
            "Find an image on the web. Use ONLY when the user explicitly asks "
            "to SEE something: 'montre-moi', 'envoie une photo de', 'une image de', "
            "'à quoi ça ressemble'. "
            "NEVER use for factual questions — use web_search instead. "
            "NEVER use when nobody asked for an image."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What image to find (e.g. 'cute cat', 'Eiffel Tower at night')",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for factual, time-sensitive information. "
            "DECISION TEST: Would the answer change depending on today's date? "
            "If YES and you don't know the current answer → search. "
            "If NO or you can answer from conversation context → do NOT search. "
            "\n"
            "SEARCH: 'c'est quoi la dernière maj d'Apex?' → YES (patch notes change) "
            "SEARCH: 'quel temps il fait à Paris?' → YES (weather changes daily) "
            "SEARCH: 'combien coûte la PS5 Pro?' → YES (prices change) "
            "NO SEARCH: 'on va dire que tu dors encore un peu' → NO (casual banter) "
            "NO SEARCH: 'ah ouais t'as raison c'est Breach' → NO (user correcting you) "
            "NO SEARCH: 'wally t'es nul' → NO (insult/joke) "
            "NO SEARCH: 'merci pour l'info' → NO (acknowledgment) "
            "NO SEARCH: 'c'est quoi ton avis sur Apex?' → NO (opinion, not fact)"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Concise factual search query in the topic's language",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class WebSearchService:
    def __init__(self, config: "Config", db: "Database"):
        self._config = config
        self._db = db
        api_key = os.environ.get("TAVILY_API_KEY", "")
        self._api_key = api_key
        self._client = None
        if api_key:
            try:
                from tavily import AsyncTavilyClient
                self._client = AsyncTavilyClient(api_key=api_key)
            except ImportError:
                logger.warning("tavily-python not installed — web search disabled")

    @property
    def available(self) -> bool:
        return self._client is not None

    async def is_quota_exceeded(self) -> bool:
        count = await self._db.count_web_searches_this_month()
        limit = self._config.tavily.monthly_limit
        if count >= int(limit * 0.8) and count < limit:
            logger.warning(
                "Tavily quota at {pct}% ({count}/{limit})",
                pct=int(count / limit * 100),
                count=count,
                limit=limit,
            )
        return count >= limit

    async def search(self, query: str) -> str:
        """Execute a web search via Tavily and return formatted results as a string."""
        if not self._client:
            return "Web search is not available (no API key or tavily-python not installed)."

        if await self.is_quota_exceeded():
            return "Web search quota exceeded for this month."

        try:
            response = await self._client.search(
                query=query,
                max_results=5,
                include_answer=True,
            )

            await self._db.log_web_search(query, len(response.get("results", [])))

            return self._format_results(response)

        except Exception as exc:
            logger.error("Tavily search error: {e}", e=exc)
            return f"Web search failed: {exc}"

    async def search_images(self, query: str) -> str:
        """Search for images via Tavily. Returns image URLs."""
        if not self._client:
            return "Web search is not available."

        if await self.is_quota_exceeded():
            return "Web search quota exceeded for this month."

        try:
            response = await self._client.search(
                query=query,
                max_results=3,
                include_images=True,
                include_answer=False,
            )

            await self._db.log_web_search(f"[image] {query}", len(response.get("images", [])))

            images = response.get("images", [])
            if not images:
                return "No images found."

            # Return URLs for the model to include in its response
            return "\n".join(images[:3])

        except Exception as exc:
            logger.error("Tavily image search error: {e}", e=exc)
            return f"Image search failed: {exc}"

    def _format_results(self, response: dict) -> str:
        parts = []
        answer = response.get("answer")
        if answer:
            parts.append(f"Summary: {answer}")

        results = response.get("results", [])
        if results:
            parts.append("\nSources:")
            for r in results[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                # Truncate content to keep token usage reasonable
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.append(f"- {title} ({url})\n  {content}")

        return "\n".join(parts) if parts else "No results found."

    def get_tool_definitions(self) -> list[dict]:
        return [WEB_SEARCH_TOOL, IMAGE_SEARCH_TOOL]
