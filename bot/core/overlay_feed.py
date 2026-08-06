"""OverlayFeed — diffuse vers l'overlay OBS ce que Wally montre au public.

Fan-out calqué sur `CognitiveFeed` : une queue par abonné plus un petit tampon
circulaire, pour qu'un client qui se connecte en cours de route ne reparte pas
d'un écran vide. La file unique de `overlay_image_queue` ne convenait pas ici :
avec un seul consommateur, ouvrir l'overlay dans OBS *et* dans un navigateur de
prévisualisation en prive un des deux.

⚠️ L'overlay s'adresse aux VIEWERS, jamais au streamer — il ne le voit pas
pendant qu'il joue. Ce module ne transporte donc que du commentaire destiné au
public (cf. docs/plans/2026-08-06-compagnon-de-stream-design.md, §0).
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Literal

from loguru import logger

# Modes d'affichage d'une bulle.
BubbleMode = Literal["speech", "thought"]

# Durée d'affichage : ~2,5 s pour cinq mots, jamais moins de 2 s ni plus de 8 s.
# L'overlay est petit et ne se relit pas : une bulle qui traîne gêne plus qu'elle
# n'informe.
_MIN_DURATION_S = 2.0
_MAX_DURATION_S = 8.0
_SECONDS_PER_WORD = 0.5


def bubble_duration(text: str) -> float:
    """Temps d'affichage d'une bulle, proportionnel à sa longueur."""
    words = len([w for w in (text or "").split() if w])
    return max(_MIN_DURATION_S, min(_MAX_DURATION_S, words * _SECONDS_PER_WORD))


class OverlayFeed:
    """Diffuseur d'événements vers les overlays connectés."""

    def __init__(self, buffer_size: int = 10, queue_maxsize: int = 30) -> None:
        self._buffer: deque[dict] = deque(maxlen=buffer_size)
        self._queues: list[asyncio.Queue] = []
        self._queue_maxsize = queue_maxsize

    # ── abonnement ────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def recent(self) -> list[dict]:
        """Derniers événements, pour amorcer un client qui vient de se connecter."""
        return list(self._buffer)

    # ── publication ───────────────────────────────────────────────────────

    def publish(self, event: dict) -> None:
        event.setdefault("ts", time.time())
        self._buffer.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Un overlay qui ne consomme plus (onglet gelé, OBS en pause) ne
                # doit pas bloquer les autres ni faire grossir la mémoire.
                logger.debug("OverlayFeed: file d'un abonné pleine, événement ignoré")

    # ── API de haut niveau ────────────────────────────────────────────────

    def say(self, text: str, mode: BubbleMode = "speech") -> None:
        """Affiche une bulle. `speech` = il réagit, `thought` = il pense tout seul."""
        text = " ".join((text or "").split())
        if not text:
            return
        self.publish({
            "type": "bubble",
            "mode": mode,
            "text": text,
            "duration": bubble_duration(text),
        })

    def think_aloud(self, text: str) -> None:
        """Raccourci : bulle de pensée (personne en vocal, ou rien à commenter)."""
        self.say(text, mode="thought")

    def thinking(self, active: bool) -> None:
        """Les trois points animés, pendant la génération."""
        self.publish({"type": "thinking", "active": bool(active)})

    def react(self, kind: str) -> None:
        """L'avatar s'emballe une seconde (raid, série de subs…)."""
        self.publish({"type": "react", "kind": kind})

    # Temps d'animation avant que le résultat ne soit lisible (voir overlay.html).
    # Un tirage doit rester à l'écran APRÈS son animation, pas pendant.
    _ANIMATION_S = {"coinflip": 1.6, "dice": 1.5, "wheel": 2.7}

    # Durée de lecture d'un résultat, une fois l'animation finie.
    _RESULT_READ_S = 10.0

    def widget(self, kind: str, **params) -> None:
        """Affiche un widget ponctuel (pile ou face, dé, uptime…).

        La durée par défaut tient compte du temps d'animation : sinon un tirage
        s'efface presque aussitôt affiché — la roue tourne 2,7 s, il ne restait
        que 2,3 s pour lire le résultat.
        """
        params.setdefault(
            "duration", self._ANIMATION_S.get(kind, 0.0) + self._RESULT_READ_S
        )
        self.publish({"type": "widget", "kind": kind, "params": params})
