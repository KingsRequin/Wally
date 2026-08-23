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


def active_stream_feed() -> "StreamFeed | None":
    """Le flux actif, ou None. Accès paresseux : le narrateur d'overlay est
    construit avant que le flux n'existe."""
    return _active


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
        # Reçoit `(description, kind)` : sans le type, l'overlay devait le
        # DEVINER depuis la phrase, et se trompait.
        self._observer: Optional[Callable[[str, str], None]] = None

    def set_observer(self, callback: Optional[Callable[[str, str], None]]) -> None:
        """Branche un observateur sur les événements retenus (None pour couper).

        Appelé avec `(description, kind)` — `kind` vaut `""` quand le producteur
        n'a pas typé son événement.
        """
        self._observer = callback

    def activate(self) -> None:
        """Enregistre ce flux comme source globale du bloc de contexte passif."""
        global _active
        _active = self

    def record(self, description: str, *, kind: str = "", notify: bool = True) -> None:
        """Empile un événement du stream (déjà rédigé en français).

        `kind` dit CE QUE c'est (`raid`, `sub`, `live_end`…). Le tampon n'en fait
        rien — il reste une suite de phrases — mais l'observateur le reçoit :
        sans lui, l'overlay devait déduire le type de la phrase, et finissait par
        annoncer des raids qui n'avaient pas eu lieu.

        `notify=False` consigne sans réveiller l'observateur : pour un fait que
        Wally vient lui-même de produire, sur lequel il n'a pas à réagir une
        seconde fois.

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
        if notify and self._observer is not None:
            try:
                self._observer(description, kind or "")
            except Exception as exc:  # noqa: BLE001 — un observateur ne casse pas le flux
                logger.warning("StreamFeed: observateur en erreur: {e!r}", e=exc)

    def record_chat(self, author: str, text: str) -> None:
        """Empile une ligne de chat du stream (perception passive uniquement)."""
        text = " ".join((text or "").split())
        if not text:
            return
        # Perception PASSIVE seulement : aucun observateur n'est branché ici.
        # `set_chat_observer` existait, annonçait servir « aux sondages et aux
        # saluts de l'overlay », et n'était appelé de nulle part — ces deux
        # fonctions sont câblées en direct depuis `twitch/handlers.py`. Retiré
        # pour ne pas laisser croire que les votes transitent par ce chemin.
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
        # Cette conclusion affirme la perception au lieu de la nier. L'ancienne
        # version — « Tu n'as RIEN à en faire : tu ne commentes pas, tu ne réagis
        # pas, tu n'en parles pas de toi-même » — était pour moitié REDONDANTE et
        # pour moitié TROMPEUSE.
        #
        # Redondante : l'initiative est déjà bloquée mécaniquement en amont.
        # `spontaneous_channel_speak_enabled: false` fait jeter tout SPEAK spontané
        # dans `cognitive_loop`, ce flux n'appelle aucun `notify_*` donc ne réveille
        # pas la cadence, et la parole spontanée est de toute façon redirigée vers
        # son salon dédié. Aucune de ces barrières ne dépend d'une phrase de prompt.
        #
        # Trompeuse : Wally l'a lue comme « je ne perçois pas », et a redemandé le
        # 2026-08-09 une capacité livrée le 05 — celle-ci même.
        #
        # Ce qui reste utile, et qu'on garde : le garde-fou anti-DIGRESSION. Une
        # réponse à une mention ne passe pas par `cognitive_loop` mais par les
        # handlers, avec ce bloc dans le prompt système — rien n'empêche alors un
        # « au fait, le chat d'Azraël dit que… » greffé sur une question sans rapport.
        lines.append(
            "Tu perçois vraiment tout ça, en fond, sans avoir à être sur Twitch. "
            "Mais tu n'ouvres pas ce sujet de toi-même : ce n'est pas à toi de "
            "raconter le live ou de commenter le chat à des gens qui ne l'ont pas "
            "sous les yeux. Si on t'en parle, en revanche, tu sais de quoi il retourne."
        )
        return "\n".join(lines)
