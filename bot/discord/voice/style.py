"""Styles de parole vocaux (Azure express-as) : selon l'humeur ou sur demande de Wally.

⚠️ Tous les styles ne sont pas disponibles sur toutes les voix, et un
`mstts:express-as` inconnu fait ÉCHOUER la synthèse — Azure ne lève pas, il rend
un flux vide, donc Wally deviendrait muet sans un mot dans les logs (cf.
`AzureTTS._stream_sync`). Le style demandé est donc toujours ramené à ce que la
voix courante sait faire.
"""
import re

# Styles réellement supportés, par voix (doc Azure « Language and voice support »,
# vérifiée le 2026-08-07). Hors MAI, **seules** Henri et Denise en supportent —
# Vivienne, Remy, Lucien, les Dragon HD et toutes les standards en ont ZÉRO.
_MAI_STYLES = frozenset({
    "angry", "confused", "determined", "disgusted", "embarrassed", "excited",
    "fearful", "happy", "hopeful", "jealous", "joyful", "regretful", "relieved",
    "sad", "shouting", "softvoice", "surprised", "whispering",
})
_STANDARD_STYLES = frozenset({"cheerful", "excited", "sad", "whispering"})

_STYLED_STANDARD_VOICES = ("fr-FR-HenriNeural", "fr-FR-DeniseNeural")


def supported_styles(voice: str | None) -> frozenset[str]:
    """Styles que cette voix accepte. Ensemble VIDE si on ne sait pas.

    Le défaut restrictif est délibéré : une voix inconnue qui recevrait un style
    invalide ne dirait plus rien du tout.
    """
    name = (voice or "").strip()
    if ":MAI-Voice-" in name:
        return _MAI_STYLES
    if name in _STYLED_STANDARD_VOICES:
        return _STANDARD_STYLES
    return frozenset()


# Repli quand la voix ne connaît pas le style voulu. Arbitrage owner
# (2026-08-07) : une voix expressive approchante vaut mieux qu'une voix plate.
_STYLE_FALLBACK = {
    "angry": "excited",       # la tension plutôt que la colère
    "shouting": "excited",
    "surprised": "excited",
    "determined": "excited",
    "happy": "cheerful",
    "joyful": "cheerful",
    "hopeful": "cheerful",
    "relieved": "cheerful",
    "fearful": "sad",
    "regretful": "sad",
    "embarrassed": "sad",
    "jealous": "sad",
    "disgusted": "sad",
    "confused": "sad",
    "softvoice": "whispering",
    "cheerful": "joyful",     # sens inverse, pour une voix MAI
    "excited": "joyful",
}


def adapt_style(style: str | None, voice: str | None) -> str | None:
    """Ramène `style` à ce que `voice` sait faire, ou None s'il n'y a rien."""
    if not style:
        return None
    allowed = supported_styles(voice)
    if not allowed:
        return None
    seen: set[str] = set()
    current: str | None = style
    # Chaîne de replis bornée : `cheerful → joyful → cheerful` boucle sinon.
    while current and current not in seen:
        if current in allowed:
            return current
        seen.add(current)
        current = _STYLE_FALLBACK.get(current)
    return None


# Émotion dominante de Wally → style Azure. Exprimé dans le vocabulaire riche des
# voix MAI ; `adapt_style()` le ramène à la voix réellement configurée.
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


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF️‍]+",
    flags=re.UNICODE,
)


def _strip_unspeakable(text: str) -> str:
    """Retire ce qui se prononce mal à l'oral (emojis, symboles décoratifs)."""
    return _EMOJI_RE.sub("", text)


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


def resolve_style(
    text: str, emotion_state: dict[str, float] | None, voice: str | None = None
) -> tuple[str | None, str]:
    """Style final + texte à dire : le tag explicite de Wally prime sur l'humeur.

    `voice` ramène le style aux capacités réelles de la voix configurée. Omis,
    le style sort tel quel — les appels historiques restent valides.
    """
    tag_style, clean = parse_style_tag(text)
    style = tag_style if tag_style is not None else mood_to_style(emotion_state)
    if voice is not None:
        style = adapt_style(style, voice)
    return style, _strip_unspeakable(_strip_brackets(clean))
