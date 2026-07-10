# bot/core/stream_watcher.py
"""Surveillance du statut live du streamer (Azrael_TTV) sur Twitch.

Un unique poller interroge `twitch_api.get_stream()` (le broadcaster « maison »,
c.-à-d. Azrael) à intervalle régulier et met en cache le dernier statut. Deux
usages :

- **À la demande** : `.status` (et l'awareness `current_stream_awareness()`
  injectée dans le prompt système) permet à Wally de SAVOIR à tout moment si
  Azrael est en live, quel jeu, quel titre — comme un ami abonné à ses notifs.
- **Notification** : sur transition live↔offline, `on_transition(old, new)` est
  appelé pour réveiller la cognition (cf. `CognitiveLoop.notify_event`).

Le premier poll établit une baseline SANS déclencher de transition : sinon un
redémarrage du bot pendant qu'Azrael streame ferait croire à tort qu'il « vient
de lancer » son live.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from loguru import logger

_OFFLINE: dict = {
    "live": False, "title": None, "category": None, "viewers": 0, "started_at": None,
}

# Watcher actif enregistré comme source globale pour l'awareness prompt — même
# patron que `read_host_metrics()` (état ambiant lu par prompts.py sans DI).
_active: "StreamWatcher | None" = None


def current_stream_status() -> Optional[dict]:
    """Dernier statut connu du streamer, ou None si aucun watcher actif."""
    return _active.status if _active is not None else None


def current_stream_awareness() -> Optional[str]:
    """Ligne d'awareness prête à injecter au prompt si le streamer est live, sinon None."""
    if _active is None:
        return None
    st = _active.status
    if not st.get("live"):
        return None
    cat = st.get("category") or "un jeu inconnu"
    line = (
        f"{_active.streamer_name} (le streamer) est EN LIVE sur Twitch en ce moment "
        f"— jeu : {cat}"
    )
    if title := st.get("title"):
        line += f", titre : « {title} »"
    line += ". Tu le sais car tu surveilles sa chaîne ; n'en parle que si c'est pertinent."
    return line


class StreamWatcher:
    """Poll périodique du statut live d'une chaîne Twitch, avec cache + transitions."""

    def __init__(
        self,
        twitch_api,
        *,
        streamer_name: str = "Azrael_TTV",
        interval: float = 60.0,
        on_transition: Optional[Callable[[dict, dict], None]] = None,
        on_poll: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._api = twitch_api
        self.streamer_name = streamer_name
        self._interval = interval
        self._on_transition = on_transition
        self._on_poll = on_poll
        self._status: dict = dict(_OFFLINE)
        self._initialized = False

    @property
    def status(self) -> dict:
        """Copie défensive du dernier statut : {live, title, category, viewers, started_at}."""
        return dict(self._status)

    def activate(self) -> None:
        """Enregistre ce watcher comme source globale de l'awareness prompt."""
        global _active
        _active = self

    async def run(self) -> None:
        """Boucle de poll — à ajouter au gather principal."""
        try:
            while True:
                await self._poll_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def _poll_once(self) -> None:
        try:
            new = await self._api.get_stream()
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("StreamWatcher poll a échoué : {e}", e=exc)
            return
        old = self._status
        self._status = new
        # Alimente les consommateurs Twitch (bot._stream_info) : un seul poll.
        if self._on_poll is not None:
            try:
                self._on_poll(new)
            except Exception as exc:  # noqa: BLE001
                logger.warning("StreamWatcher on_poll a échoué : {e}", e=exc)
        # Premier poll = baseline silencieuse (pas de fausse notif au boot).
        if not self._initialized:
            self._initialized = True
            return
        if bool(new.get("live")) != bool(old.get("live")):
            logger.info(
                "Stream {name} : {a} → {b}",
                name=self.streamer_name,
                a="live" if old.get("live") else "offline",
                b="live" if new.get("live") else "offline",
            )
            if self._on_transition is not None:
                try:
                    self._on_transition(old, new)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("StreamWatcher on_transition a échoué : {e}", e=exc)
