# bot/core/scrape.py
from __future__ import annotations

import os
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.llm.base import BaseLLMClient
    from bot.db.database import Database

_MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
    ".mp3", ".wav", ".ogg", ".flac",
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
)
_MEDIA_HOSTS = ("cdn.discordapp.com", "media.discordapp.net")

_SUMMARY_SYSTEM = (
    "Tu résumes une page web pour un assistant. Restitue les informations factuelles "
    "essentielles en français, en 2 à 4 phrases, sans préambule ni mise en forme superflue. "
    "Conserve chiffres, noms et dates importants."
)

SCRAPE_TOOL = {
    "type": "function",
    "function": {
        "name": "scrape_url",
        "description": (
            "Lis le contenu COMPLET d'une page web précise à partir de son URL. "
            "Utilise quand tu as une URL et que tu dois en connaître le contenu détaillé "
            "(article, patch notes, documentation). N'utilise PAS pour chercher une info "
            "générale — utilise web_search pour ça."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "L'URL exacte de la page à lire (http/https).",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}


class ScrapeService:
    def __init__(self, config: "Config", db: "Database", summarizer: "BaseLLMClient | None" = None):
        self._config = config
        self._db = db
        self._summarizer = summarizer
        self._base_url = os.environ.get("FIRECRAWL_API_URL", "").rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._base_url) and bool(self._config.firecrawl.enabled)

    def is_scrapable_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if any(h in host for h in _MEDIA_HOSTS):
            return False
        path = parsed.path.lower()
        if path.endswith(_MEDIA_EXTENSIONS):
            return False
        return True

    async def daily_limit_reached(self) -> bool:
        count = await self._db.count_scrapes_today()
        return count >= self._config.firecrawl.daily_limit

    async def scrape(self, url: str) -> str:
        if not self.available:
            return "Le scraping n'est pas disponible (Firecrawl non configuré)."
        if not self.is_scrapable_url(url):
            return "Cette URL ne peut pas être lue (média ou lien non supporté)."
        try:
            if await self.daily_limit_reached():
                return "Limite quotidienne de scraping atteinte."
        except Exception as exc:
            logger.warning("daily_limit_reached error: {e}", e=exc)
            return "Impossible de vérifier la limite quotidienne de scraping."

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/scrape",
                    json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Firecrawl scrape error for {u}: {e}", u=url, e=exc)
            return f"Impossible de lire la page ({url})."

        markdown = (data.get("data") or {}).get("markdown") or ""
        if not markdown.strip():
            return f"La page ne contient pas de texte lisible ({url})."

        await self._db.log_scrape(url)
        return await self._apply_budget(markdown, url)

    async def _apply_budget(self, markdown: str, url: str) -> str:
        approx_tokens = len(markdown) // 4
        if approx_tokens <= self._config.firecrawl.inline_max_tokens:
            return f"Contenu de {url} :\n{markdown.strip()}"

        if self._summarizer is None:
            # Pas de résumeur : on tronque proprement.
            budget_chars = self._config.firecrawl.inline_max_tokens * 4
            return f"Contenu (tronqué) de {url} :\n{markdown[:budget_chars].strip()}…"

        try:
            summary = await self._summarizer.complete(
                _SUMMARY_SYSTEM,
                [{"role": "user", "content": markdown[:24000]}],
                purpose="scrape_summary",
                max_tokens=400,
            )
        except Exception as exc:
            logger.warning("Scrape summary failed for {u}: {e}", u=url, e=exc)
            budget_chars = self._config.firecrawl.inline_max_tokens * 4
            return f"Contenu (tronqué) de {url} :\n{markdown[:budget_chars].strip()}…"

        return f"Résumé de {url} :\n{summary.strip()}"

    def get_tool_definitions(self) -> list[dict]:
        return [SCRAPE_TOOL]
