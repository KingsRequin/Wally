"""STT streaming distant — client du serveur RealtimeSTT GPU (docs/voice/REMOTE_STT_API.md).

Architecture :
- `RemoteSTTSession` : une connexion WebSocket = un locuteur = un recorder dédié côté serveur.
  Attend `ready`, streame l'audio PCM 16 kHz mono int16 LE au fil de l'eau, envoie `flush`
  quand le VAD local signale la fin de parole, reçoit `partial` (live) et `final` (précis).
- `RemoteStreamingSTT` : orchestre une session par locuteur, respecte la limite de connexions
  du serveur, et bascule un locuteur sur le STT batch CPU local (fallback) si le serveur est
  injoignable (cache ~30 s) ou plein (error / close 1013).

L'ordre des trames audio est garanti par une file unique par session drainée par une seule
tâche d'envoi : `enqueue()`/`enqueue_flush()` sont synchrones (appelables depuis le thread du
sink via `loop.call_soon_threadsafe`) et ne font qu'empiler ; l'envoi réel est sérialisé.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Awaitable, Callable

import websockets
from loguru import logger

_FLUSH = object()  # sentinelle « force la fin de l'énoncé » dans la file d'envoi
_PREBUF_MAX = 250  # ~5 s de frames de 20 ms bufferisées avant `ready` (borne mémoire)
_BACKOFF_MAX_MULT = 4  # plafond du backoff injoignable = health_cache_s × 4 (ex. 30s → 120s max)

# Énoncés en attente de transcription locale avant abandon. Deux, c'est déjà
# ~4 s de retard sur ce CPU ; au-delà, la réaction arrive hors sujet.
_MAX_PENDING_FALLBACK = 2


class RemoteSTTSession:
    """Une connexion WebSocket vers le serveur STT distant, pour un seul locuteur."""

    def __init__(
        self,
        url: str,
        *,
        on_partial: Callable[[str], None],
        on_final: Callable[[str, float], None],
        on_close: Callable[[], None] | None = None,
        connect=None,
        open_timeout: float = 5.0,
        ready_timeout: float = 35.0,
        ping_interval: float = 5.0,
        ping_timeout: float = 5.0,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._url = url
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_close = on_close
        self._connect = connect or websockets.connect
        self._open_timeout = open_timeout
        self._ready_timeout = ready_timeout
        # Keepalive court : une coupure brutale (PC éteint / câble débranché, sans close TCP)
        # est détectée en ~ping_interval+ping_timeout s au lieu des ~20-40 s par défaut.
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._now = now_fn or time.monotonic
        self._ws = None
        self._sendq: asyncio.Queue = asyncio.Queue()
        self._ready_evt = asyncio.Event()
        self._recv_task: asyncio.Task | None = None
        self._sender_task: asyncio.Task | None = None
        self._closed = False
        self._t_flush: float | None = None  # horodatage du dernier flush (latence du final)
        self.ready = False
        self.server_full = False
        self.unreachable = False

    async def start(self) -> bool:
        """Connecte, attend `ready`. Retourne True si prêt à recevoir l'audio, False sinon
        (injoignable → `unreachable`, ou serveur plein → `server_full`)."""
        try:
            self._ws = await self._connect(
                self._url, max_size=None, open_timeout=self._open_timeout,
                ping_interval=self._ping_interval, ping_timeout=self._ping_timeout,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("RemoteSTTSession: connexion à {u} a échoué: {e}", u=self._url, e=e)
            self.unreachable = True
            return False
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._sender_task = asyncio.create_task(self._sender_loop())
        try:
            await asyncio.wait_for(self._ready_evt.wait(), self._ready_timeout)
        except asyncio.TimeoutError:
            logger.warning("RemoteSTTSession: pas de `ready` après {t}s", t=self._ready_timeout)
            # Compté comme INJOIGNABLE. Sans ce drapeau, ni `_arm_unreachable_cache`
            # ni le repli batch ne s'armaient : la session était retirée, et la
            # frame suivante — 20 ms plus tard — en rouvrait une, qui attendrait
            # 35 s de plus. Un serveur qui accepte le TCP sans jamais répondre
            # (modèle en cours de chargement, process figé) entretenait ainsi
            # deux WebSockets en vol en permanence, backoff jamais déclenché.
            self.unreachable = True
            return False
        return self.ready and not self.server_full

    def enqueue(self, pcm: bytes) -> None:
        """Empile un chunk audio (sync). Envoyé après `ready`, dans l'ordre d'empilement."""
        if self._closed:
            return
        if self._sendq.qsize() > _PREBUF_MAX and not self.ready:
            return  # serveur pas encore prêt et buffer plein → on lâche (borne mémoire)
        self._sendq.put_nowait(pcm)

    def enqueue_flush(self) -> None:
        """Empile une demande de `flush` (force la fin de l'énoncé courant)."""
        if self._closed:
            return
        self._sendq.put_nowait(_FLUSH)

    async def _sender_loop(self) -> None:
        await self._ready_evt.wait()
        if not self.ready:  # error / fermeture avant ready → rien à envoyer
            return
        try:
            while not self._closed:
                item = await self._sendq.get()
                if item is _FLUSH:
                    self._t_flush = self._now()
                    await self._ws.send(json.dumps({"type": "flush"}))
                else:
                    await self._ws.send(item)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("RemoteSTTSession: envoi a échoué: {e}", e=e)

    async def _recv_loop(self) -> None:
        try:
            async for msg in self._ws:
                if isinstance(msg, (bytes, bytearray)):
                    continue  # le serveur n'émet que du texte
                try:
                    obj = json.loads(msg)
                except (ValueError, TypeError):
                    continue
                kind = obj.get("type")
                if kind == "ready":
                    self.ready = True
                    self._ready_evt.set()
                elif kind == "partial":
                    self._safe_partial(obj.get("text", ""))
                elif kind == "final":
                    stt_ms = (self._now() - self._t_flush) * 1000 if self._t_flush else 0.0
                    self._t_flush = None
                    self._safe_final(obj.get("text", ""), stt_ms)
                elif kind == "error":
                    msgtxt = str(obj.get("message", ""))
                    logger.warning("RemoteSTTSession: erreur serveur: {m}", m=msgtxt)
                    if "full" in msgtxt.lower():
                        self.server_full = True
                    self._ready_evt.set()  # débloque start()
        except asyncio.CancelledError:
            raise
        except websockets.ConnectionClosed as e:
            rcvd = getattr(e, "rcvd", None)
            if getattr(rcvd, "code", None) == 1013:
                self.server_full = True
        except Exception as e:  # noqa: BLE001
            logger.warning("RemoteSTTSession: réception a échoué: {e}", e=e)
        finally:
            self._ready_evt.set()  # ne jamais laisser start() bloqué
            # Connexion fermée sans close() volontaire = session perdue (serveur tombé en
            # pleine conversation) → on prévient le manager pour qu'il bascule en fallback.
            if not self._closed and self._on_close is not None:
                try:
                    self._on_close()
                except Exception as e:  # noqa: BLE001
                    logger.warning("RemoteSTTSession on_close a échoué: {e}", e=e)

    def _safe_partial(self, text: str) -> None:
        try:
            self._on_partial(text)
        except Exception as e:  # noqa: BLE001
            logger.warning("RemoteSTTSession on_partial a échoué: {e}", e=e)

    def _safe_final(self, text: str, stt_ms: float) -> None:
        try:
            self._on_final(text, stt_ms)
        except Exception as e:  # noqa: BLE001
            logger.warning("RemoteSTTSession on_final a échoué: {e}", e=e)

    async def close(self) -> None:
        self._closed = True
        for task in (self._sender_task, self._recv_task):
            if task is not None:
                task.cancel()
        for task in (self._sender_task, self._recv_task):
            if task is not None:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass


class RemoteStreamingSTT:
    """Orchestre les sessions STT distantes par locuteur, avec fallback batch CPU local.

    Câblage : le service positionne `on_partial(speaker_id, text)` et `on_final` (coroutine
    `async (speaker_id, text, stt_ms)`). `feed_sync`/`speech_end_sync` sont synchrones et
    appelables depuis la boucle (via le sink) ; elles ne bloquent jamais.
    """

    def __init__(
        self,
        url: str,
        *,
        fallback,
        max_connections: int = 2,
        idle_timeout: float = 30.0,
        health_cache_s: float = 30.0,
        open_timeout: float = 5.0,
        ready_timeout: float = 35.0,
        connect=None,
        now_fn: Callable[[], float] | None = None,
        session_factory=None,
        priority_speakers: set[str] | None = None,
    ) -> None:
        self._url = url
        self._fallback = fallback
        self._max_connections = max_connections
        # Discord IDs qui passent devant quand les places manquent : ceux au nom
        # de qui Wally agit (`voice.requesters` — le créateur et le streamer).
        # Sans eux, l'attribution est au premier qui ouvre la bouche, et le
        # 2026-08-14 le streamer a passé une heure sur le repli local pendant
        # que deux invités se partageaient le GPU.
        self._priority_speakers: set[str] = set(priority_speakers or ())
        self._idle_timeout = idle_timeout
        self._health_cache_s = health_cache_s
        self._open_timeout = open_timeout
        self._ready_timeout = ready_timeout
        self._connect = connect
        self._now = now_fn or time.monotonic
        self._session_factory = session_factory or self._default_session_factory
        self._sessions: dict[str, RemoteSTTSession] = {}
        self._start_tasks: dict[str, asyncio.Task] = {}
        self._fallback_speakers: set[str] = set()
        # Énoncés en cours de transcription locale — borne la file, cf.
        # _MAX_PENDING_FALLBACK.
        self._pending_fallback = 0
        self._last_activity: dict[str, float] = {}
        # Références fortes des tâches détachées. La boucle asyncio ne garde
        # qu'une référence FAIBLE : une tâche non retenue peut être collectée en
        # vol. Sur le chemin du fallback — emprunté par CHAQUE énoncé dans la
        # configuration par défaut — cela perdait la parole ET laissait
        # `_pending_fallback` incrémenté (le `finally` ne s'exécute pas), de quoi
        # rendre Wally sourd en deux collectes.
        self._detached: set[asyncio.Task] = set()
        # Posé par `close_all()` : sans lui, `feed_sync` rouvrait une session sur
        # un pipeline fermé (le thread audio tourne encore pendant l'await de
        # fermeture). Seul `RemoteSTTSession` avait son drapeau, pas le manager.
        self._ferme = False
        self._unreachable_until: float = 0.0
        self._consecutive_unreachable: int = 0  # backoff exponentiel : ↑ à chaque échec, remis à 0 au succès
        # Câblés par le service.
        self.on_partial: Callable[[str, str], None] | None = None
        self.on_final: Callable[[str, str, float], Awaitable[None]] | None = None

    def _default_session_factory(self, sid: str) -> RemoteSTTSession:
        return RemoteSTTSession(
            self._url,
            on_partial=lambda text, _sid=sid: self._emit_partial(_sid, text),
            on_final=lambda text, ms, _sid=sid: self._emit_final(_sid, text, ms),
            on_close=lambda _sid=sid: self._on_session_lost(_sid),
            connect=self._connect,
            open_timeout=self._open_timeout,
            ready_timeout=self._ready_timeout,
            now_fn=self._now,
        )

    async def warmup(self) -> None:
        """Prépare les DEUX chemins, puis rend la main.

        Le repli local charge son modèle (plusieurs secondes de CPU), et une
        session distante est ouverte à blanc pour que le serveur charge les
        siens — c'est son message `ready` qui l'annonce. Sans cette ouverture,
        le coût était payé à la première phrase, après qu'on ait cru Wally prêt.
        """
        warm = getattr(self._fallback, "warmup", None)
        if warm is not None:
            await warm()
        await self.warm_remote()

    async def warm_remote(self) -> bool:
        """Ouvre une session à blanc et attend le `ready` du serveur.

        Retourne True si le serveur distant est prêt. False s'il est injoignable
        ou plein : le repli local prendra le relais, et il est déjà chaud.
        """
        session = self._session_factory("__warmup__")
        try:
            pret = await session.start()
        except Exception as exc:  # noqa: BLE001 — un préchauffage raté n'est pas fatal
            logger.debug("RemoteStreamingSTT: préchauffage distant en échec: {e}", e=exc)
            return False
        finally:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
        logger.info(
            "RemoteStreamingSTT: serveur distant {e}",
            e="prêt" if pret else "indisponible — repli local",
        )
        return bool(pret)

    # ------------------------------------------------------------------
    # Entrées synchrones (depuis le sink / la boucle)
    # ------------------------------------------------------------------

    def feed_sync(self, speaker_id: str, pcm: bytes) -> None:
        """Streame un chunk audio pour ce locuteur (ouvre la session distante à la demande)."""
        if self._ferme:
            return
        now = self._now()
        self._last_activity[speaker_id] = now
        if speaker_id in self._fallback_speakers:
            return  # routé batch → traité au speech_end via le segment VAD
        sess = self._sessions.get(speaker_id)
        if sess is None:
            if not self._remote_allowed(now) and not self._ceder_une_place(speaker_id, now):
                self._fallback_speakers.add(speaker_id)
                return
            sess = self._session_factory(speaker_id)
            self._sessions[speaker_id] = sess
            self._start_tasks[speaker_id] = asyncio.create_task(self._open_and_watch(speaker_id, sess))
        sess.enqueue(pcm)

    def speech_end_sync(self, speaker_id: str, segment: bytes) -> None:
        """Fin de parole détectée par le VAD local : flush distant, ou batch local en fallback."""
        sess = self._sessions.get(speaker_id)
        # `ready` et non `is not None` : `feed_sync` enregistre la session AVANT
        # de savoir si elle s'ouvre. Quand le serveur est mort, l'énoncé partait
        # dans une session qui n'aboutirait jamais — et `_open_and_watch` la
        # retire sans transcrire ce qu'elle contenait. La parole était donc
        # perdue, après 5 à 35 s d'attente.
        if sess is not None and sess.ready:
            sess.enqueue_flush()  # réduit la latence du final (envoyé dès que prêt)
            return
        # Pas de session distante (fallback ou ouverture échouée) → transcription batch du segment.
        self._fallback_speakers.discard(speaker_id)  # réessaiera le distant au prochain énoncé
        # File saturée : on ABANDONNE l'énoncé plutôt que de l'empiler. Mesuré en
        # live à trois locuteurs, la file montait à 35 s de retard — à ce
        # décalage, Wally « réagit » à une phrase que tout le monde a oubliée.
        # Pour un compagnon, la fraîcheur prime sur l'exhaustivité.
        if self._pending_fallback >= _MAX_PENDING_FALLBACK:
            logger.debug("STT local saturé — énoncé abandonné (file pleine)")
            return
        self._pending_fallback += 1
        self._detach(self._fallback_transcribe(speaker_id, segment))

    # ------------------------------------------------------------------
    # Cycle de vie des sessions
    # ------------------------------------------------------------------

    def _detach(self, coro) -> None:
        """Lance une coroutine en tâche de fond, référence gardée.

        `asyncio.create_task` seul ne suffit pas : la boucle ne retient qu'une
        référence faible, et une tâche non gardée peut être collectée en vol.
        """
        task = asyncio.create_task(coro)
        self._detached.add(task)
        task.add_done_callback(self._detached.discard)

    def _remote_allowed(self, now: float) -> bool:
        return now >= self._unreachable_until and len(self._sessions) < self._max_connections

    def _ceder_une_place(self, speaker_id: str, now: float) -> bool:
        """Libère une place pour un locuteur prioritaire. Vrai si c'est fait.

        Les places du serveur distant sont comptées (VRAM), et l'attribution
        était au premier arrivé. Le 2026-08-14, les deux places sont restées à
        deux invités pendant qu'Azraël — le streamer, celui à qui Wally doit
        répondre — transcrivait par lots de trente secondes sur le CPU : ses
        demandes n'atteignaient plus personne, une heure durant.

        Un invité cède, jamais un prioritaire : entre eux, rien ne les départage
        et se déloger mutuellement ferait pire. Le délogé repart sur le repli
        local — `speech_end_sync` le remet dans la course à l'énoncé suivant.
        """
        if speaker_id not in self._priority_speakers:
            return False
        if now < self._unreachable_until:
            # Le serveur ne répond pas : prendre la place d'un invité ne
            # donnerait rien à l'un et coûterait sa session à l'autre.
            return False
        victime = next(
            (sid for sid in self._sessions if sid not in self._priority_speakers), None
        )
        if victime is None:
            return False
        logger.info("RemoteStreamingSTT: place cédée par {v} à {s} (prioritaire)",
                    v=victime, s=speaker_id)
        self._fallback_speakers.add(victime)
        sess = self._sessions.pop(victime, None)
        self._start_tasks.pop(victime, None)
        if sess is not None:
            self._detach(sess.close())
        return True

    def _arm_unreachable_cache(self) -> None:
        """Arme le cache « injoignable » avec un backoff exponentiel borné.

        Plus le serveur reste mort, plus on espace les tentatives (chacune gâche ~open_timeout
        de latence sur une parole) : 30s → 60s → 120s (plafond). Remis à zéro dès qu'une
        connexion réussit (`_open_and_watch`)."""
        self._consecutive_unreachable += 1
        mult = min(2 ** (self._consecutive_unreachable - 1), _BACKOFF_MAX_MULT)
        self._unreachable_until = self._now() + self._health_cache_s * mult

    async def _open_and_watch(self, speaker_id: str, sess: RemoteSTTSession) -> None:
        ok = await sess.start()
        if ok:
            self._consecutive_unreachable = 0  # serveur revenu → on repart du cache de base
            return
        # Échec : retire la session (le slot se libère), met en cache si injoignable.
        self._sessions.pop(speaker_id, None)
        self._start_tasks.pop(speaker_id, None)
        if sess.unreachable:
            self._arm_unreachable_cache()
            logger.warning("RemoteStreamingSTT: serveur injoignable, prochaine tentative dans {t}s",
                           t=round(self._unreachable_until - self._now()))
        elif sess.server_full:
            # Sans ça, le locuteur retentait une connexion à chaque frame de
            # 20 ms : boucle connect / `error: full` / close pendant tout
            # l'énoncé. Le fallback local le reprend, et `speech_end_sync` le
            # retire de ce jeu au prochain énoncé pour réessayer le distant.
            self._fallback_speakers.add(speaker_id)
            logger.info("RemoteStreamingSTT: serveur plein → {s} en local", s=speaker_id)
        await sess.close()

    def _on_session_lost(self, speaker_id: str) -> None:
        """Une session distante établie a perdu sa connexion.

        On la retire, ce qui libère la place, et le locuteur repart sur le batch
        local (`feed_sync`/`speech_end_sync`).

        Le cache « injoignable » n'est armé QUE si plus aucune session ne tient :
        une session qui saute n'est pas un serveur mort. Le 2026-08-14, celle
        d'Azraël est tombée trois fois pendant que le serveur répondait aux deux
        autres locuteurs — et à chaque fois le backoff (30 → 60 → 120 s) mettait
        TOUT LE MONDE sur le repli local, y compris ceux dont la session vivait.
        Il suffit d'une session survivante pour savoir que le serveur est debout.
        """
        sess = self._sessions.pop(speaker_id, None)
        if sess is None:
            return  # déjà retirée (fermeture volontaire, idle, ou double notification)
        self._start_tasks.pop(speaker_id, None)
        if not self._sessions:
            self._arm_unreachable_cache()
            logger.warning("RemoteStreamingSTT: session {s} perdue, plus aucune "
                           "session vivante → fallback batch {t}s",
                           s=speaker_id, t=round(self._unreachable_until - self._now()))
        else:
            logger.warning("RemoteStreamingSTT: session {s} perdue → repli local "
                           "(le serveur répond encore à {n} autre(s))",
                           s=speaker_id, n=len(self._sessions))
        self._detach(sess.close())

    async def _fallback_transcribe(self, speaker_id: str, segment: bytes) -> None:
        t0 = self._now()
        try:
            try:
                text = await self._fallback.transcribe(segment)
            except Exception as e:  # noqa: BLE001
                logger.warning("RemoteStreamingSTT fallback batch a échoué: {e}", e=e)
                text = ""
            stt_ms = (self._now() - t0) * 1000
            if text and self.on_final is not None:
                await self.on_final(speaker_id, text, stt_ms)
        finally:
            # Sans ce décrément garanti, une seule exception bloquerait la file
            # pour de bon et Wally deviendrait sourd.
            self._pending_fallback = max(0, self._pending_fallback - 1)

    def _emit_partial(self, speaker_id: str, text: str) -> None:
        if self.on_partial is not None and text:
            try:
                self.on_partial(speaker_id, text)
            except Exception as e:  # noqa: BLE001
                logger.warning("RemoteStreamingSTT on_partial a échoué: {e}", e=e)

    def _emit_final(self, speaker_id: str, text: str, stt_ms: float) -> None:
        if self.on_final is not None and text:
            self._detach(self.on_final(speaker_id, text, stt_ms))

    async def maintain(self, interval: float = 5.0) -> None:
        """Ferme les sessions inactives (libère un slot / la VRAM côté serveur).

        Rouvre aussi le manager : `close_all()` le verrouille, et `join()`
        RÉUTILISE le même objet d'une session vocale à l'autre — sans cette
        levée, le STT serait mort dès le premier `leave()`.
        """
        self._ferme = False
        try:
            while True:
                await asyncio.sleep(interval)
                now = self._now()
                for sid in list(self._sessions):
                    if now - self._last_activity.get(sid, now) > self._idle_timeout:
                        logger.info("RemoteStreamingSTT: session {s} inactive → fermeture", s=sid)
                        await self._close_session(sid)
        except asyncio.CancelledError:
            pass

    async def _close_session(self, speaker_id: str) -> None:
        sess = self._sessions.pop(speaker_id, None)
        self._start_tasks.pop(speaker_id, None)
        self._last_activity.pop(speaker_id, None)
        if sess is not None:
            await sess.close()

    async def close_all(self) -> None:
        # Verrouillé d'abord : plus aucune session ne s'ouvre à partir d'ici.
        self._ferme = True
        # Les transcriptions détachées meurent avec le pipeline : un `final`
        # produit par un pipeline remplacé remontait au service via `on_final`
        # et était traité comme une parole courante.
        for task in list(self._detached):
            task.cancel()
        self._detached.clear()
        self._pending_fallback = 0
        # Le backoff « injoignable » (`_unreachable_until`,
        # `_consecutive_unreachable`) survit VOLONTAIREMENT : `close_all()` est
        # appelé à chaque `leave()`, et l'effacer ferait re-tenter un serveur
        # mort à chaque join. Un changement de config, lui, reconstruit l'objet
        # entier via `build_streaming_stt` — le backoff repart donc à neuf de
        # lui-même, sans qu'on ait à l'oublier ici.
        # Annuler les ouvertures EN COURS aussi : une session en attente de
        # `ready` (jusqu'à 35 s) survivait à la fermeture et se rattachait à un
        # pipeline remplacé.
        for task in list(self._start_tasks.values()):
            task.cancel()
        self._start_tasks.clear()
        for sid in list(self._sessions):
            await self._close_session(sid)
        self._fallback_speakers.clear()
        # Ces deux-là restaient renseignés d'une session à l'autre : `maintain()`
        # relisait des horodatages de locuteurs disparus.
        self._last_activity.clear()
