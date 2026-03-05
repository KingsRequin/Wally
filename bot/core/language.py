# bot/core/language.py
from __future__ import annotations

from langdetect import detect, LangDetectException
from loguru import logger


class LanguageDetector:
    def __init__(self, default_lang: str = "fr"):
        self._default = default_lang

    def detect(self, text: str) -> str:
        if not text or not text.strip():
            return self._default
        try:
            return detect(text)
        except LangDetectException:
            logger.debug(
                "Language detection failed, using default {lang}", lang=self._default
            )
            return self._default
