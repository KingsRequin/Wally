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

from bot.core.secret_guard import redact

# Modes d'affichage d'une bulle.
BubbleMode = Literal["speech", "thought"]

# Durée d'affichage. Le plancher gouverne en pratique : une bulle fait au plus
# 90 caractères, soit ~15 mots, donc toutes durent 10 s. Un viewer ne fixe pas
# l'overlay — il faut que la bulle survive à un aller-retour vers le gameplay.
_MIN_DURATION_S = 10.0
_MAX_DURATION_S = 12.0
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
        """Événements encore VIVANTS, pour amorcer un client qui se connecte.

        L'amorçage sert à ne pas démarrer sur un écran vide au milieu d'un live.
        Mais un widget est éphémère : rejouer un dé lancé il y a dix minutes
        parce que la connexion SSE a sauté donne l'impression que l'overlay
        tourne en boucle. On ne renvoie donc que ce qui serait encore à l'écran.
        """
        now = time.time()
        alive: list[dict] = []
        for event in self._buffer:
            age = now - float(event.get("ts") or now)
            params = event.get("params") or {}
            span = float(event.get("duration") or params.get("duration") or 0)
            # Une partie en cours ne périme pas : le pendu doit revenir tel quel
            # chez un OBS qui se reconnecte, sans quoi la grille disparaissait
            # pour de bon à la première coupure SSE.
            if params.get("sticky") is True:
                alive.append(dict(event))
                continue
            # `thinking` et `react` n'ont pas de durée : ils sont instantanés et
            # ne doivent jamais être rejoués.
            if span <= 0 or age > span:
                continue
            # Durée RESTANTE, pas la durée initiale : une bulle publiée il y a
            # 9 s sur 10 restait 10 s de plus chez un client qui reconnecte,
            # décalant tout ce qui suit.
            trimmed = dict(event)
            left = round(span - age, 2)
            if "duration" in trimmed:
                trimmed["duration"] = left
            params = trimmed.get("params")
            if isinstance(params, dict) and "duration" in params:
                trimmed["params"] = {**params, "duration": left}
            alive.append(trimmed)
        return alive

    # ── publication ───────────────────────────────────────────────────────

    def publish(self, event: dict) -> None:
        event.setdefault("ts", time.time())
        self._purge_sticky_obsoletes(event)
        self._buffer.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Un overlay qui ne consomme plus (onglet gelé, OBS en pause) ne
                # doit pas bloquer les autres ni faire grossir la mémoire.
                logger.debug("OverlayFeed: file d'un abonné pleine, événement ignoré")

    def _purge_sticky_obsoletes(self, event: dict) -> None:
        """Retire du tampon les états collants d'un widget qui vient de se clore.

        Un widget `sticky` est réémis par `recent()` SANS jamais périmer — c'est
        ce qui permet à une partie en cours de revenir chez un OBS qui se
        reconnecte. Mais rien ne les retirait à la fin de la partie : le dernier
        événement (`won`/`lost`) est publié en `sticky=False` avec 12 s de durée,
        donc filtré par l'âge au bout de 12 s, tandis que TOUS les coups
        précédents restaient éligibles. Une reconnexion tardive rejouait alors un
        état INTERMÉDIAIRE d'une partie terminée, sans minuteur — à l'écran
        jusqu'à ce qu'un autre widget le remplace. Exactement le symptôme que le
        `sticky` devait éviter, à l'envers.
        """
        if event.get("type") != "widget" or (event.get("params") or {}).get("sticky") is True:
            return
        kind = event.get("kind")
        restants = [
            e for e in self._buffer
            if not (e.get("type") == "widget" and e.get("kind") == kind
                    and (e.get("params") or {}).get("sticky") is True)
        ]
        if len(restants) != len(self._buffer):
            self._buffer.clear()
            self._buffer.extend(restants)

    # ── API de haut niveau ────────────────────────────────────────────────

    def say(self, text: str, mode: BubbleMode = "speech") -> None:
        """Affiche une bulle. `speech` = il réagit, `thought` = il pense tout seul."""
        text = redact(" ".join((text or "").split()))
        if not text:
            return
        # Point de passage unique de TOUTES les bulles : sans cette trace, ce que
        # l'overlay a réellement dit pendant un live est introuvable après coup.
        logger.info("Overlay [{m}] : {t}", m=mode, t=text)
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

    def clear(self) -> None:
        """Retire immédiatement ce qui est à l'écran.

        Le tampon est vidé en même temps, et pas seulement l'écran : `recent()`
        rejoue les événements encore vivants à tout client qui se connecte. Sans
        ça, un overlay rouvert dans la seconde qui suit une annulation remontait
        le widget qu'on venait de retirer — et la reconnexion SSE automatique
        d'OBS suffisait à le faire réapparaître tout seul.
        """
        self._buffer.clear()
        self.publish({"type": "clear"})

    def widget(self, kind: str, /, **params) -> None:
        """Affiche un widget ponctuel (pile ou face, dé, uptime…).

        La durée par défaut tient compte du temps d'animation : sinon un tirage
        s'efface presque aussitôt affiché — la roue tourne 2,7 s, il ne restait
        que 2,3 s pour lire le résultat.
        """
        params.setdefault(
            "duration", self._ANIMATION_S.get(kind, 0.0) + self._RESULT_READ_S
        )
        self.publish({"type": "widget", "kind": kind, "params": params})
