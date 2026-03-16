# bot/core/language.py
from __future__ import annotations

from langdetect import detect_langs, LangDetectException
from langdetect.detector_factory import DetectorFactory
from loguru import logger

DetectorFactory.seed = 0  # make detection deterministic

_MIN_CONFIDENCE = 0.75  # below this, fall back to default


class LanguageDetector:
    def __init__(self, default_lang: str = "fr"):
        self._default = default_lang

    def detect(self, text: str) -> str:
        if not text or not text.strip():
            return self._default
        try:
            results = detect_langs(text)
            if results and results[0].prob >= _MIN_CONFIDENCE:
                return str(results[0].lang)
            return self._default
        except LangDetectException:
            logger.debug(
                "Language detection failed, using default {lang}", lang=self._default
            )
            return self._default
