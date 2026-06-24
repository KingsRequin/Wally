# bot/core/vision.py
"""Service de vision — analyse réelle des images entrantes.

Wally tourne en DeepSeek-only, un LLM AVEUGLE : il accepte `image_urls` mais
les ignore, ce qui le pousse à inventer le contenu des images. Ce service est
la seule source de « vue » du bot : il décrit factuellement une image via un
modèle OpenAI multimodal et extrait les stats des screenshots de trackers de
jeu, pour que le LLM principal commente des FAITS réels au lieu de broder.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from loguru import logger

from bot.core.llm.base import FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE
from bot.intelligence.prompts import load_prompt

if TYPE_CHECKING:
    from bot.core.llm.openai_client import OpenAILLMClient

_DEFAULT_PROMPT = (
    "Décris précisément et factuellement le contenu de l'image. Si c'est un "
    "screenshot de stats de jeu, extrais les données chiffrées visibles "
    "(rang, K/D/A, score, agent...). N'invente rien ; signale ce qui est illisible."
)


class VisionService:
    """Analyse visuelle d'images via un client OpenAI multimodal.

    Indisponible si aucun client n'est fourni (clé OpenAI absente) ; dans ce
    cas `analyze()` retourne None et l'appelant continue sans analyse.
    """

    def __init__(self, client: "OpenAILLMClient | None", max_tokens: int = 400) -> None:
        self._client = client
        self._max_tokens = max_tokens

    @property
    def available(self) -> bool:
        return self._client is not None

    async def analyze(
        self,
        image_urls: Iterable[str] | None,
        caption: str = "",
        purpose: str = "image_analysis",
    ) -> str | None:
        """Retourne une analyse factuelle de la/des image(s), ou None.

        `caption` = le texte qui accompagne l'image (oriente l'analyse).
        """
        urls = [u for u in (image_urls or []) if u]
        if not self._client or not urls:
            return None

        system = load_prompt("image_analyze_system", _DEFAULT_PROMPT)
        user_text = (caption or "").strip() or "Décris cette image."
        try:
            result = await self._client.complete(
                system,
                [{"role": "user", "content": user_text}],
                purpose=purpose,
                image_urls=urls,
                max_tokens=self._max_tokens,
            )
        except Exception as e:  # défensif : ne jamais casser le pipeline de réponse
            logger.warning("VisionService.analyze a échoué : {e}", e=e)
            return None

        text = (result or "").strip()
        # complete() renvoie un message de repli en cas d'échec API → on le filtre
        # pour ne pas injecter de faux « faits » dans le contexte.
        if not text or text in (FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE):
            return None
        return text
