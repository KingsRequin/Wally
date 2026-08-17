"""WallyAudioSink — reçoit le PCM par locuteur, segmente via VAD, déclenche un callback."""
import asyncio
import threading
import time

from discord.ext import voice_recv
from loguru import logger

from collections import deque

from bot.discord.voice.audio import FRAME_BYTES, VadSegmenter, to_stt_format

# Ce qu'on garde sous le coude avant que le VAD ne reconnaisse la parole, en
# frames de 20 ms. Le VAD ne décide qu'APRÈS coup : sans ce rattrapage, l'attaque
# du mot partirait à la poubelle avec le silence qui la précède — « Wally »
# devient « ally ». 300 ms couvre la latence de décision de webrtcvad avec de la
# marge, pour 9,6 ko par locuteur.
_PREROLL_FRAMES = 15


class WallyAudioSink(voice_recv.AudioSink):
    """Reçoit le PCM par locuteur, segmente par VAD, déclenche un callback async par segment.

    Deux modes :
    - batch (défaut) : `on_segment(user, pcm16k_mono)` est appelé (coroutine) sur chaque
      segment de parole clos par le VAD.
    - streaming : si `on_frame` et `on_speech_end` sont fournis, chaque frame brute de 20 ms
      est émise au fil de l'eau via `on_frame(user, frame)` (pour le STT streaming distant), et
      la fin de parole (segment VAD clos) via `on_speech_end(user, segment)` — au lieu de
      `on_segment`. Ces deux callbacks sont synchrones et planifiés sur la boucle via
      `call_soon_threadsafe` (ordre FIFO préservé), car `write()` tourne dans un thread audio.

    Fin de parole à l'horloge (`flush_idle`) : Discord **supprime les silences** — quand le
    locuteur se tait, plus aucun paquet n'arrive, donc `write()` ne tourne plus et le VAD ne
    voit jamais les frames de silence qui closent l'énoncé. Sans cela, l'énoncé ne se termine
    jamais (segment batch jamais émis ; `flush` distant jamais envoyé → le serveur boucle).
    `flush_idle()`, appelé périodiquement sur la boucle, clôt l'énoncé d'un locuteur dont
    aucune frame n'est arrivée depuis `silence_timeout_s`. Thread-safe vs `write()` via un lock.

    Anti-larsen : l'audio est ignoré pendant que `service.is_speaking` est True.
    Le service est passé directement au sink pour éviter de passer par bot.voice_service.
    """

    def __init__(self, service, aggressiveness: int, on_segment, loop: asyncio.AbstractEventLoop,
                 on_frame=None, on_speech_end=None,
                 silence_timeout_s: float = 0.6, now_fn=None) -> None:
        super().__init__()
        self._service = service
        self._aggr = aggressiveness
        self._on_segment = on_segment
        self._on_frame = on_frame
        self._on_speech_end = on_speech_end
        self._loop = loop
        self._silence_timeout_s = silence_timeout_s
        self._now = now_fn or time.monotonic
        self._segmenters: dict[int, VadSegmenter] = {}
        self._frame_buf: dict[int, bytearray] = {}
        self._last_frame_ts: dict[int, float] = {}  # monotonic du dernier frame reçu par locuteur
        self._users: dict[int, object] = {}         # id → membre (pour émettre depuis flush_idle)
        self._lock = threading.Lock()               # write() (thread audio) vs flush_idle() (boucle)
        # Le pouls de l'écoute. Sans lui, « Wally n'entend rien » couvre trois
        # pannes que rien ne distingue : aucun audio ne descend de Discord, le
        # VAD ne referme jamais d'énoncé, ou le modèle rend du vide. Les deux
        # premières ne laissaient AUCUNE trace — c'est ce silence-là qui coûte
        # une heure de live à chaque fois.
        self._frames_recues = 0
        self._segments_emis = 0
        # PAR LOCUTEUR, parce que le total seul ne dit pas d'où vient le flot :
        # le premier relevé a montré 61 fois le temps réel en audio, ce qui ne
        # peut PAS venir du nombre de personnes présentes.
        self._frames_par_locuteur: dict[int, int] = {}
        # Le relais vers le STT distant, par locuteur : ce qu'on retient avant
        # l'attaque, et si l'on est en train de relayer.
        self._preroll: dict[int, deque] = {}
        self._relaye: dict[int, bool] = {}

    def _frames_a_relayer(self, uid: int, frame: bytes, en_parole: bool) -> tuple:
        """Ce qui part au STT distant pour cette frame — souvent rien.

        Le sink relayait TOUTES les frames, sans jamais demander son avis au VAD
        qu'il interroge pourtant juste après. Discord ne coupe le silence que si
        l'émetteur le fait : un micro ouvert sur un ventilateur, et le flux ne
        s'arrête jamais. Le serveur distant avalait ainsi cent quatre secondes
        d'audio intégralement silencieuses entre deux prises de parole, sa file
        montait à 167, il cessait de répondre aux pings, et la session mourait
        sur `keepalive ping timeout` — la boucle de « crash ».
        """
        anneau = self._preroll.setdefault(uid, deque(maxlen=_PREROLL_FRAMES))
        if not en_parole:
            self._relaye[uid] = False
            anneau.append(frame)
            return ()
        if self._relaye.get(uid):
            return (frame,)
        # Début de parole : on rattrape l'attaque du mot avec ce qui précède.
        self._relaye[uid] = True
        debut = tuple(anneau)
        anneau.clear()
        return debut + (frame,)

    def pouls(self) -> tuple[int, int, dict[int, int]]:
        """(frames reçues, énoncés clos, frames par locuteur) puis remise à zéro."""
        with self._lock:
            valeurs = (self._frames_recues, self._segments_emis,
                       dict(self._frames_par_locuteur))
            self._frames_recues = self._segments_emis = 0
            self._frames_par_locuteur.clear()
        return valeurs

    def wants_opus(self) -> bool:
        """Retourne False : on veut du PCM décodé (pas Opus)."""
        return False

    def write(self, user, data: voice_recv.VoiceData) -> None:
        """Appelé pour chaque paquet audio reçu. user peut être None.

        On NE coupe PAS l'écoute pendant que Wally parle : `_on_segment` filtre alors
        pour ne garder que les ordres d'arrêt (barge-in). Cela transcrit aussi la voix
        de Wally renvoyée par les micros (larsen), mais elle est ignorée côté brain.
        """
        if user is None:
            return
        try:
            if not data.pcm:
                return
            pcm16 = to_stt_format(data.pcm)  # 48k stéréo → 16k mono
            streaming = self._on_frame is not None
            with self._lock:
                self._last_frame_ts[user.id] = self._now()
                self._users[user.id] = user
                buf = self._frame_buf.setdefault(user.id, bytearray())
                buf.extend(pcm16)
                seg = self._segmenters.setdefault(user.id, VadSegmenter(self._aggr))
                while len(buf) >= FRAME_BYTES:
                    frame = bytes(buf[:FRAME_BYTES])
                    del buf[:FRAME_BYTES]
                    self._frames_recues += 1
                    self._frames_par_locuteur[user.id] = (
                        self._frames_par_locuteur.get(user.id, 0) + 1)
                    # Le VAD juge D'ABORD : c'est son verdict qui décide de ce
                    # qui part au serveur distant. L'ordre était inverse, et le
                    # silence partait avec le reste.
                    out = seg.feed(frame)
                    if streaming:
                        for relayee in self._frames_a_relayer(
                                user.id, frame, seg.en_parole):
                            self._loop.call_soon_threadsafe(
                                self._on_frame, user, relayee)
                    if out:
                        self._segments_emis += 1
                        self._emit_segment(user, out)
        except Exception as e:  # noqa: BLE001
            logger.warning("WallyAudioSink.write a échoué: {e}", e=e)

    def flush_idle(self) -> None:
        """Clôt l'énoncé d'un locuteur silencieux depuis `silence_timeout_s` (Discord coupe le
        silence → le VAD ne voit jamais la fin). À appeler périodiquement sur la boucle."""
        now = self._now()
        with self._lock:
            for uid, seg in self._segmenters.items():
                last = self._last_frame_ts.get(uid)
                if last is None or now - last < self._silence_timeout_s:
                    continue
                out = seg.flush()
                if out:
                    # Compté ici aussi : la PLUPART des énoncés se ferment par
                    # ce chemin, Discord coupant le silence qui les clôturerait.
                    # Ne compter que ceux du VAD aurait montré « 0 énoncé » sur
                    # une écoute qui marche.
                    self._segments_emis += 1
                    self._emit_segment(self._users.get(uid), out)
                self._last_frame_ts.pop(uid, None)  # ne re-flush pas tant qu'aucune frame ne revient

    def _emit_segment(self, user, segment: bytes) -> None:
        """Aiguille un segment clos vers le bon callback (streaming → on_speech_end, sinon batch).

        Toujours planifié sur la boucle (jamais exécuté inline) : appelable depuis le thread
        audio (`write`) comme depuis la boucle (`flush_idle`)."""
        if user is None:
            return
        if self._on_frame is not None:
            self._loop.call_soon_threadsafe(self._on_speech_end, user, segment)
        else:
            asyncio.run_coroutine_threadsafe(self._on_segment(user, segment), self._loop)

    def cleanup(self) -> None:
        with self._lock:
            self._segmenters.clear()
            self._frame_buf.clear()
            self._last_frame_ts.clear()
            self._users.clear()
            self._preroll.clear()
            self._relaye.clear()
