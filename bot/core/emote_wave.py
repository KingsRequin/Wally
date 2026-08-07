"""Vagues d'emotes — quand tout le chat spamme la même chose.

Le signal n'est pas le nombre de messages mais le nombre de PERSONNES : dix
« KEKW » d'un seul viewer, c'est un habitué qui s'amuse ; quatre viewers
différents en dix secondes, c'est le chat qui réagit ensemble. Seul le second
mérite l'écran.

La détection est mécanique, comme celle des compteurs : elle passe sur chaque
ligne de chat sans coûter d'appel LLM.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from loguru import logger

# Une vague est resserrée dans le temps ; au-delà, c'est juste un emote courant.
_WINDOW_S = 12.0

# En dessous, ce n'est pas une vague mais deux personnes d'accord.
_MIN_PEOPLE = 4

# Après une vague, on ne resignale pas le même emote tout de suite : il reste
# souvent en fond pendant une minute.
_COOLDOWN_S = 90.0

# Un « emote » ici : un mot sans espace, sans URL, assez court pour en être un.
# Les emotes Twitch (KEKW, PogChamp) et les emotes de chaîne (azrael74HYPE) sont
# en CamelCase ou en capitales ; les mots ordinaires sont écartés par la casse.
_TOKEN = re.compile(r"^[A-Za-z0-9_]{3,30}$")


def _looks_like_emote(token: str) -> bool:
    """Vrai si le mot ressemble à un emote plutôt qu'à un mot français.

    Un emote porte une majuscule ailleurs qu'en tête (PogChamp, azrael74HYPE) ou
    est tout en capitales (KEKW). « Bonjour » et « ptdr » ne passent pas.
    """
    if not _TOKEN.match(token):
        return False
    if token.isupper() and len(token) >= 3:
        return True
    return any(c.isupper() for c in token[1:])


class EmoteWaveDetector:
    """Repère qu'un même emote déferle, et ne le signale qu'une fois."""

    def __init__(self, min_people: int = _MIN_PEOPLE, window_s: float = _WINDOW_S) -> None:
        self._min_people = min_people
        self._window = window_s
        # emote → file de (instant, auteur)
        self._seen: dict[str, deque] = defaultdict(deque)
        self._announced: dict[str, float] = {}

    def feed(self, author: str, text: str, *, now: float | None = None) -> str | None:
        """Retourne l'emote qui déferle, ou None. Un seul signalement par vague."""
        now = time.time() if now is None else now
        author = (author or "").lower()
        if not author:
            return None
        for token in set((text or "").split()):
            if not _looks_like_emote(token):
                continue
            hits = self._seen[token]
            hits.append((now, author))
            while hits and now - hits[0][0] > self._window:
                hits.popleft()
            people = {a for _, a in hits}
            if len(people) < self._min_people:
                continue
            if now - self._announced.get(token, 0.0) < _COOLDOWN_S:
                continue
            self._announced[token] = now
            hits.clear()
            logger.info("Vague d'emote : {t} ({n} personnes)", t=token, n=len(people))
            return token
        return None
