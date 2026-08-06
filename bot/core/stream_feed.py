# bot/core/stream_feed.py
"""Flux passif des événements du stream (perception d'ambiance, pas de réaction).

Wally suit le live du streamer « du coin de l'œil » : lancement/fin, changement
de jeu ou de titre, vagues d'audience, raids/subs/bits, et les dernières lignes
du chat. Tout atterrit dans un tampon roulant horodaté, restitué au prompt sous
forme de bloc de CONTEXTE PASSIF.

C'est volontairement une voie SANS retour vers l'action : rien ici n'appelle
`notify_activity` / `notify_event`, donc le flux ne réveille jamais la cadence
cognitive et ne déclenche aucune prise de parole. Wally SAIT ce qui se passe sur
le stream ; il n'en parle que si on l'interpelle là-dessus.

Même patron que `stream_watcher` : un flux actif s'enregistre comme source
globale (`activate()`), et `current_stream_feed_block()` le rend lisible par
`prompts.py` / l'`AttentionAgent` sans injection de dépendance.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Optional

from loguru import logger

# Tampons volontairement courts : c'est du bruit de fond, pas un historique.
MAX_EVENTS = 20
MAX_CHAT = 8
# Au-delà, l'événement n'est plus « ce qui se passe en ce moment ».
EVENT_TTL = 7200.0   # 2 h
CHAT_TTL = 900.0     # 15 min — le chat vieillit beaucoup plus vite

_active: "StreamFeed | None" = None


def current_stream_feed_block(include_chat: bool = True) -> Optional[str]:
    """Bloc de flux prêt à injecter au prompt, ou None si rien à dire."""
    if _active is None:
        return None
    return _active.render(include_chat=include_chat) or None


def _age(seconds: float) -> str:
    """Ancienneté lisible : « à l'instant », « il y a 12 min », « il y a 2 h »."""
    if seconds < 60:
        return "à l'instant"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"il y a {minutes} min"
    return f"il y a {minutes // 60} h"


class StreamFeed:
    """Tampon roulant des événements du stream, rendu comme contexte passif."""

    def __init__(
        self,
        streamer_name: str = "",
        *,
        max_events: int = MAX_EVENTS,
        max_chat: int = MAX_CHAT,
        event_ttl: float = EVENT_TTL,
        chat_ttl: float = CHAT_TTL,
    ) -> None:
        self.streamer_name = streamer_name
        self._events: deque[tuple[float, str]] = deque(maxlen=max_events)
        self._chat: deque[tuple[float, str, str]] = deque(maxlen=max_chat)
        self._event_ttl = event_ttl
        self._chat_ttl = chat_ttl
        # Observateur notifié à chaque nouvel événement retenu (doublons exclus).
        # Sert à l'overlay de stream, qui réagit en direct. Reste passif : le
        # flux garde sa vocation de contexte, il ne déclenche rien de lui-même.
        self._observer: Optional[Callable[[str], None]] = None

    def set_observer(self, callback: Optional[Callable[[str], None]]) -> None:
        """Branche un observateur sur les événements retenus (None pour couper)."""
        self._observer = callback

    def activate(self) -> None:
        """Enregistre ce flux comme source globale du bloc de contexte passif."""
        global _active
        _active = self

    def record(self, description: str) -> None:
        """Empile un événement du stream (déjà rédigé en français).

        Le doublon consécutif est ignoré : un poll qui « flappe » (catégorie qui
        revient à sa valeur précédente puis repart) ne doit pas remplir le tampon
        de la même ligne.
        """
        description = (description or "").strip()
        if not description:
            return
        if self._events and self._events[-1][1] == description:
            return
        self._events.append((time.monotonic(), description))
        logger.debug("StreamFeed: {d}", d=description)
        if self._observer is not None:
            try:
                self._observer(description)
            except Exception as exc:  # noqa: BLE001 — un observateur ne casse pas le flux
                logger.warning("StreamFeed: observateur en erreur: {e}", e=exc)

    def record_chat(self, author: str, text: str) -> None:
        """Empile une ligne de chat du stream (perception passive uniquement)."""
        text = " ".join((text or "").split())
        if not text:
            return
        self._chat.append((time.monotonic(), author, text[:160]))

    def _fresh_events(self, now: float) -> list[tuple[float, str]]:
        return [(ts, d) for ts, d in self._events if now - ts <= self._event_ttl]

    def _fresh_chat(self, now: float) -> list[tuple[float, str, str]]:
        return [(ts, a, t) for ts, a, t in self._chat if now - ts <= self._chat_ttl]

    def render(self, include_chat: bool = True) -> str:
        """Bloc texte du flux, ou "" si rien de frais à montrer.

        `include_chat=False` sur le chemin Twitch de la chaîne home, où le
        prélude porte déjà les lignes de chat (évite le doublon).
        """
        now = time.monotonic()
        events = self._fresh_events(now)
        chat = self._fresh_chat(now) if include_chat else []
        if not events and not chat:
            return ""

        who = self.streamer_name or "le streamer"
        lines = [
            "\n--- Flux du stream (perception passive) ---",
            f"Tu suis le live de {who} en fond, comme un onglet resté ouvert dans un "
            f"coin de ton écran.",
        ]
        for ts, desc in events:
            lines.append(f"· {_age(now - ts)} — {desc}")
        if chat:
            lines.append("Dernières lignes du chat du stream :")
            for _ts, author, text in chat:
                lines.append(f"· [{author}] {text}")
        lines.append(
            "Tu n'as RIEN à en faire : tu ne commentes pas, tu ne réagis pas, tu n'en "
            "parles pas de toi-même. C'est du bruit de fond qui enrichit ce que tu "
            "comprends de la situation — tu ne t'en sers que si on t'interroge "
            "directement là-dessus."
        )
        return "\n".join(lines)
