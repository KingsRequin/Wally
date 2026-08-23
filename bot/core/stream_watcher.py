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
- **Flux passif** : `on_event(description, kind=…, notify=…)` reçoit CHAQUE changement observé au
  fil du live (lancement, fin, changement de jeu ou de titre, vague d'audience)
  pour alimenter le `StreamFeed` — contexte d'ambiance, sans réveil cognitif.

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

# Sensibilité de la perception d'audience : une vague est notable si elle change
# l'ordre de grandeur (±50 %) ET dépasse un plancher absolu (sinon 2→4 viewers
# sur un stream qui démarre remplirait le flux de bruit). Constantes de
# perception, pas de comportement.
VIEWER_SWING_RATIO = 0.5
VIEWER_SWING_MIN = 10


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
        # Signature réelle : `(description, *, kind: str, notify: bool)`. Elle
        # était annotée à UN argument alors que l'appel en passe trois depuis
        # le typage des événements, et le repli qui rattrapait le TypeError a
        # été retiré : une réimplémentation écrite d'après cette annotation
        # aurait levé, absorbée en `logger.warning` — flux passif muet, sans
        # cause visible.
        on_event: Optional[Callable[..., None]] = None,
    ) -> None:
        self._api = twitch_api
        self.streamer_name = streamer_name
        self._interval = interval
        self._on_transition = on_transition
        self._on_poll = on_poll
        self._on_event = on_event
        self._status: dict = dict(_OFFLINE)
        self._initialized = False
        # Repère d'audience : dernière valeur ayant donné lieu à un événement de
        # vague. Remis au compteur à chaque démarrage de live.
        self._viewers_mark: int = 0

    @property
    def status(self) -> dict:
        """Copie défensive du dernier statut : {live, title, category, viewers, started_at}."""
        return dict(self._status or {})

    @property
    def a_sonde(self) -> bool:
        """Un relevé au moins est passé — avant lui, `status` n'est qu'un défaut.

        Ce défaut porte `live: False`, ce qui n'est pas « le stream est
        éteint » mais « on ne sait pas encore ». Le duel Apex rembourse et
        abandonne quand le live se coupe : sans cette distinction, un rebuild
        en plein duel (fréquents ici) solderait le duel repris avant même le
        premier poll, en accusant un stream parfaitement allumé.
        """
        return self._initialized

    def activate(self) -> None:
        """Enregistre ce watcher comme source globale de l'awareness prompt."""
        global _active
        _active = self

    async def run(self) -> None:
        """Boucle de poll — à ajouter au gather principal."""
        try:
            while True:
                # Le try n'entourait QUE l'appel API : toute erreur de traitement
                # (ex. un `get_stream()` renvoyant None) tuait le poller pour de
                # bon et remontait dans le `gather` principal, sans
                # `return_exceptions`. Un veilleur ne meurt pas d'un poll raté.
                try:
                    await self._poll_once()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("StreamWatcher: poll en erreur : {e!r}", e=exc)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def _poll_once(self) -> None:
        try:
            new = await self._api.get_stream()
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.warning("StreamWatcher poll a échoué : {e!r}", e=exc)
            return
        if not isinstance(new, dict):
            logger.warning("StreamWatcher: statut inattendu {t}, poll ignoré",
                           t=type(new).__name__)
            return
        if new.get("unknown"):
            # L'API n'a pas répondu : on ne SAIT pas, ce qui n'est pas la même
            # chose que « le live est fini ». Conclure à l'arrêt faisait quitter
            # le vocal à Wally sur une simple coupure réseau. On garde l'état
            # précédent et on retentera au prochain tour.
            logger.debug("StreamWatcher: statut indisponible, poll ignoré")
            return
        old = self._status
        self._status = new
        # Alimente les consommateurs Twitch (bot._stream_info) : un seul poll.
        if self._on_poll is not None:
            try:
                self._on_poll(new)
            except Exception as exc:  # noqa: BLE001
                logger.warning("StreamWatcher on_poll a échoué : {e!r}", e=exc)
        # Premier poll = baseline silencieuse (pas de fausse notif au boot).
        if not self._initialized:
            self._initialized = True
            self._viewers_mark = int(new.get("viewers") or 0)
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
                    logger.warning("StreamWatcher on_transition a échoué : {e!r}", e=exc)
        self._emit_feed_events(old, new)

    def _emit(self, description: str, *, kind: str = "", notify: bool = True) -> None:
        """Pousse une ligne dans le flux passif — jamais bloquant.

        `kind` dit ce qu'est l'événement (`live_start`, `game_change`…) ; sans
        lui, l'overlay devait le déduire de la phrase.

        `notify=False` pour ce qui doit être SU sans être commenté.

        Le consommateur attendu est `StreamFeed.record`, dont c'est la signature.
        Un repli qui rattrapait `TypeError` pour ré-appeler `on_event(description)`
        a été retiré : il ne distinguait pas une signature incompatible d'un
        `TypeError` levé PAR le callback, et republiait alors le même événement.
        """
        if self._on_event is None:
            return
        try:
            self._on_event(description, kind=kind, notify=notify)
        except Exception as exc:  # noqa: BLE001
            logger.warning("StreamWatcher on_event a échoué : {e!r}", e=exc)

    def _emit_feed_events(self, old: dict, new: dict) -> None:
        """Traduit l'écart entre deux polls en événements de flux passif.

        Le watcher ne voyait jusqu'ici que la bascule live↔offline : un
        changement de jeu ou de titre EN COURS de live était écrasé dans le cache
        sans laisser de trace. C'est pourtant le « gameplay » que Wally doit
        percevoir en fond.
        """
        if self._on_event is None:
            return
        name = self.streamer_name or "le streamer"
        was_live, is_live = bool(old.get("live")), bool(new.get("live"))

        if is_live and not was_live:
            desc = f"{name} a lancé son live"
            cat = new.get("category")
            title = new.get("title")
            if cat:
                desc += f" (jeu : {cat}"
                desc += f", titre : « {title} »)" if title else ")"
            elif title:
                desc += f" (titre : « {title} »)"
            self._viewers_mark = int(new.get("viewers") or 0)
            self._emit(desc, kind="live_start")
            return
        if was_live and not is_live:
            self._viewers_mark = 0
            self._emit(f"{name} a terminé son live.", kind="live_end")
            return
        if not is_live:
            return

        # En cours de live : ce qui bouge dans le stream lui-même.
        old_cat, new_cat = old.get("category"), new.get("category")
        if new_cat and new_cat != old_cat:
            self._emit(
                f"{name} change de jeu : {old_cat} → {new_cat}" if old_cat
                else f"{name} lance {new_cat}",
                kind="game_change",
            )
        old_title, new_title = old.get("title"), new.get("title")
        if new_title and new_title != old_title:
            self._emit(f"{name} a changé le titre du stream : « {new_title} »", kind="title_change")

        viewers = int(new.get("viewers") or 0)
        delta = viewers - self._viewers_mark
        if abs(delta) >= VIEWER_SWING_MIN and abs(delta) >= self._viewers_mark * VIEWER_SWING_RATIO:
            verb = "monte" if delta > 0 else "retombe"
            # Perception seule : le compteur de spectateurs fluctue tout seul, il
            # ne dit rien de neuf au public et faisait commenter Wally dans le
            # vide. Il reste dans le contexte, il ne déclenche plus rien.
            self._emit(
                f"l'audience {verb} : {self._viewers_mark} → {viewers} spectateurs",
                kind="audience",
                notify=False,
            )
            self._viewers_mark = viewers
