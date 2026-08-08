# bot/core/secret_guard.py
"""Mots que Wally connaît mais ne doit pas écrire, tant qu'ils sont en jeu.

Le mot d'un pendu en cours est dans son contexte : sans lui, il ne peut ni
donner un second indice ni dire où en est la partie. La consigne de ne pas
l'écrire voyage collée au mot — mais une consigne se contourne, et il suffit
d'une fois pour gâcher la partie de tout le chat.

Ceci est la ceinture, pas les bretelles : un filtre mécanique appliqué aux
points de sortie. Il ne retire rien à ce que Wally SAIT ; il l'empêche
seulement de le publier.

Volontairement bête : pas de regex savante, pas de tolérance aux fautes. Ce qui
est visé est le cas réel — le modèle qui lâche le mot tel quel, ou espacé, au
milieu d'une phrase.
"""
from __future__ import annotations

import re
import unicodedata

from loguru import logger

# Secrets actifs : forme repliée → masque affiché à la place.
_SECRETS: dict[str, str] = {}

_MASK = "[…]"


def _fold(text: str) -> str:
    """Minuscules sans accents : « FLÈCHE » et « fleche » sont le même mot."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def guard_secret(word: str) -> None:
    """Interdit ce mot en sortie jusqu'à `release_secret`."""
    folded = _fold(word).strip()
    # Deux lettres, c'est déjà un mot courant : masquer « et » ou « le » abîmerait
    # toutes les phrases sans rien protéger.
    if len(folded) < 3:
        return
    _SECRETS[folded] = _MASK
    logger.info("SecretGuard : un mot de {n} lettres est protégé en sortie", n=len(folded))


def release_secret(word: str) -> None:
    """Lève la protection (partie gagnée, perdue ou abandonnée)."""
    _SECRETS.pop(_fold(word).strip(), None)


def clear_secrets() -> None:
    _SECRETS.clear()


# Le secret est stocké replié, mais le texte sortant, lui, est accentué :
# chercher « fleche » ne trouverait pas « flèche ». Chaque lettre accepte donc
# ses variantes.
_VARIANTS = {
    "a": "aàáâãä", "c": "cç", "e": "eéèêë", "i": "iíìîï",
    "n": "nñ", "o": "oóòôõö", "u": "uúùûü", "y": "yÿ",
}


def _pattern_for(folded: str) -> str:
    """Motif tolérant aux accents, à la casse et à l'épellation.

    Un mot épelé — « o r d i n a t e u r » — est un mot dit. Les séparateurs
    admis entre lettres restent l'espace, le tiret, le point : de quoi attraper
    l'épellation sans masquer une phrase entière par accident.
    """
    letters = [f"[{_VARIANTS.get(c, c)}]" if c.isalpha() else re.escape(c)
               for c in folded]
    return r"[\s\-_.]*".join(letters)


def redact(text: str) -> str:
    """Masque les secrets actifs dans un texte sortant.

    Rien à protéger — le cas courant — et le texte ressort tel quel.
    """
    if not _SECRETS or not text:
        return text
    out = text
    for folded in list(_SECRETS):
        out, count = re.subn(_pattern_for(folded), _MASK, out, flags=re.IGNORECASE)
        if count:
            logger.warning(
                "SecretGuard : un mot protégé a été retiré d'un message sortant "
                "({n} occurrence(s))", n=count,
            )
    return out
