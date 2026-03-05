# tests/test_language.py
from bot.core.language import LanguageDetector


def test_detect_french():
    det = LanguageDetector(default_lang="fr")
    result = det.detect("Bonjour, comment vas-tu aujourd'hui ?")
    assert result == "fr"


def test_detect_english():
    det = LanguageDetector(default_lang="fr")
    result = det.detect("Hello, how are you doing today? Nice to meet you.")
    assert result == "en"


def test_fallback_on_empty():
    det = LanguageDetector(default_lang="fr")
    result = det.detect("")
    assert result == "fr"


def test_fallback_on_single_char():
    det = LanguageDetector(default_lang="en")
    result = det.detect("a")
    # either detected or fallback — must be a 2-char ISO code
    assert isinstance(result, str) and len(result) == 2


def test_custom_default():
    det = LanguageDetector(default_lang="es")
    result = det.detect("")
    assert result == "es"
