"""Styles de parole vocaux (Azure express-as) : selon l'humeur ou sur demande de Wally."""
import re

# Émotion dominante de Wally → style Azure (voix Marc:MAI-Voice-2).
_MOOD_STYLE = {
    "anger": "angry",
    "joy": "joyful",
    "sadness": "sad",
    "curiosity": "excited",
    "boredom": "softvoice",
}
_MOOD_THRESHOLD = 0.4  # l'émotion dominante doit dépasser ce seuil pour colorer la voix


def mood_to_style(emotion_state: dict[str, float] | None) -> str | None:
    """Retourne le style Azure correspondant à l'émotion dominante, ou None si neutre."""
    if not isinstance(emotion_state, dict) or not emotion_state:
        return None
    dominant, value = max(emotion_state.items(), key=lambda kv: kv[1])
    if value < _MOOD_THRESHOLD:
        return None
    return _MOOD_STYLE.get(dominant)


# Tags de ton que Wally peut placer en tête de phrase → style Azure.
_TAG_STYLE = {
    "murmure": "whispering", "chuchote": "whispering", "chuchotement": "whispering",
    "crie": "shouting", "crier": "shouting", "hurle": "shouting",
    "doux": "softvoice", "doucement": "softvoice", "calme": "softvoice",
    "joyeux": "joyful", "content": "joyful", "heureux": "joyful",
    "triste": "sad",
    "enerve": "angry", "énervé": "angry", "colere": "angry", "colère": "angry", "fache": "angry",
    "excite": "excited", "excité": "excited",
    "surpris": "surprised",
    "peur": "fearful", "apeure": "fearful", "apeuré": "fearful",
}

_TAG_RE = re.compile(r"^\s*[\[(]\s*([a-zà-ÿ]+)\s*[\])]\s*", re.IGNORECASE)


def parse_style_tag(text: str) -> tuple[str | None, str]:
    """Détecte un tag de ton en tête de phrase (ex '[murmure] ...').

    Retourne (style_azure | None, texte_nettoyé). Si le tag est inconnu, il est
    retiré quand même (on ne le lit pas à voix haute) mais le style reste None.
    """
    if not text:
        return None, text
    m = _TAG_RE.match(text)
    if not m:
        return None, text
    tag = m.group(1).lower()
    style = _TAG_STYLE.get(tag)
    clean = text[m.end():].lstrip()
    return style, (clean or text)


def _strip_brackets(text: str) -> str:
    """Retire les crochets résiduels (tags/didascalies non reconnus) pour ne pas les lire à voix haute.

    - '[rire]' / '[il soupire]' (didascalie courte) → supprimée entièrement.
    - '[une phrase entière entre crochets]' → on garde le texte, sans les crochets.
    """
    # Didascalies courtes (≤ 3 mots) entre crochets → supprimées.
    text = re.sub(r"\[[^\]]{0,40}\]", lambda m: "" if len(m.group(0).split()) <= 3 else m.group(0), text)
    # Crochets résiduels isolés → retirés (le texte reste).
    text = text.replace("[", "").replace("]", "")
    return re.sub(r"\s{2,}", " ", text).strip()


def resolve_style(text: str, emotion_state: dict[str, float] | None) -> tuple[str | None, str]:
    """Style final + texte à dire : le tag explicite de Wally prime sur l'humeur."""
    tag_style, clean = parse_style_tag(text)
    style = tag_style if tag_style is not None else mood_to_style(emotion_state)
    return style, _strip_brackets(clean)
