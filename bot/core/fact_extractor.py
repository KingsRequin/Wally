import re
import unicodedata

_MIN_LENGTH = 15

_INTERJECTION_PATTERNS = [
    re.compile(r"^lo+l+$"),
    re.compile(r"^md(r+)$"),
    re.compile(r"^ptd(r+)$"),
    re.compile(r"^x+d+$"),
    re.compile(r"^ha(ha)+$"),
    re.compile(r"^o+k+$"),
    re.compile(r"^gg+$"),
    re.compile(r"^wp+$"),
    re.compile(r"^a+h+$"),
    re.compile(r"^o+h+$"),
    re.compile(r"^ri+p+$"),
    re.compile(r"^ou+i+$"),
    re.compile(r"^no+n+$"),
    re.compile(r"^\^{2,}$"),
    re.compile(r"^\+1$"),
]


def _is_emoji_only(text: str) -> bool:
    for ch in text:
        if ch.isspace():
            continue
        if unicodedata.category(ch) not in ("So", "Sk", "Mn", "Cf"):
            return False
    return True


def _is_interjection(word: str) -> bool:
    return any(p.match(word) for p in _INTERJECTION_PATTERNS)


def _is_memorable(text: str) -> bool:
    text = text.strip()
    if len(text) < _MIN_LENGTH:
        return False
    if _is_emoji_only(text):
        return False
    words = text.lower().split()
    if not words:
        return False
    if all(_is_interjection(w) for w in words):
        return False
    return True
