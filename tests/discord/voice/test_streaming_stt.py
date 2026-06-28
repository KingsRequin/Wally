"""Tests du STT streaming distant (RemoteSTTSession + RemoteStreamingSTT).

Un faux serveur WebSocket (websockets.serve) imite le contrat RealtimeSTT documenté
dans docs/voice/REMOTE_STT_API.md : handshake `ready`, audio binaire 16 kHz, contrôle
`flush`, messages `partial`/`final`, rejet `error`+close 1013 quand le serveur est plein.
"""
import asyncio
import json
import socket

import pytest
import websockets

from bot.discord.voice.streaming import RemoteSTTSession, RemoteStreamingSTT


# ----------------------------------------------------------------------
# Faux serveur RealtimeSTT
# ----------------------------------------------------------------------


class FakeSTTServer:
    """Faux serveur STT configurable pour les tests."""

    def __init__(self, *, send_ready=True, max_connections=99, ready_delay=0.0,
                 final_text="salut wally", partials=("sa", "salut")):
        self.send_ready = send_ready
        self.max_connections = max_connections
        self.ready_delay = ready_delay
        self.final_text = final_text
        self.partials = partials
        self.live_connections = 0
        self.total_connections = 0
        self.received_audio: list[bytes] = []  # tous chunks binaires reçus, ordre global
        self.received_control: list[dict] = []
        self._server = None
        self.host = "127.0.0.1"
        self.port = None

    async def start(self):
        self._server = await websockets.serve(self._handler, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws, *args):
        self.total_connections += 1
        self.live_connections += 1
        try:
            if self.live_connections > self.max_connections:
                await ws.send(json.dumps({"type": "error", "message": "server full (2 connexions max)"}))
                await ws.close(code=1013)
                return
            if self.ready_delay:
                await asyncio.sleep(self.ready_delay)
            if self.send_ready:
                await ws.send(json.dumps({"type": "ready"}))
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    self.received_audio.append(bytes(msg))
                    continue
                obj = json.loads(msg)
                self.received_control.append(obj)
                if obj.get("type") == "flush":
                    for p in self.partials:
                        await ws.send(json.dumps({"type": "partial", "text": p}))
                    await ws.send(json.dumps({"type": "final", "text": self.final_text}))
        except websockets.ConnectionClosed:
            pass
        finally:
            self.live_connections -= 1


@pytest.fixture
async def server():
    srv = FakeSTTServer()
    await srv.start()
    yield srv
    await srv.stop()


async def _wait_until(cond, timeout=2.0, interval=0.02):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if cond():
            return True
        await asyncio.sleep(interval)
    return cond()


def _free_port() -> int:
    """Retourne un port TCP libre (refusera la connexion → injoignable, sans hang)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ----------------------------------------------------------------------
# RemoteSTTSession
# ----------------------------------------------------------------------


async def test_session_attend_ready_puis_streame_l_audio_dans_l_ordre(server):
    finals, partials = [], []
    sess = RemoteSTTSession(
        server.url, on_partial=partials.append,
        on_final=lambda t, ms: finals.append(t),
    )
    assert await sess.start() is True
    assert sess.ready is True

    for i in range(3):
        sess.enqueue(bytes([i]) * 640)
    await _wait_until(lambda: len(server.received_audio) >= 3)
    await sess.close()

    assert server.received_audio == [bytes([0]) * 640, bytes([1]) * 640, bytes([2]) * 640]


async def test_session_flush_force_le_final(server):
    finals, partials = [], []
    sess = RemoteSTTSession(
        server.url, on_partial=partials.append,
        on_final=lambda t, ms: finals.append((t, ms)),
    )
    await sess.start()
    sess.enqueue(b"\x01\x02" * 320)
    sess.enqueue_flush()

    await _wait_until(lambda: len(finals) == 1)
    await sess.close()

    assert any(c.get("type") == "flush" for c in server.received_control)
    assert finals[0][0] == "salut wally"
    assert partials == ["sa", "salut"]


async def test_session_serveur_plein_echoue_au_start():
    srv = FakeSTTServer(max_connections=0)  # rejette toute connexion (1013)
    await srv.start()
    try:
        sess = RemoteSTTSession(srv.url, on_partial=lambda t: None, on_final=lambda t, ms: None)
        assert await sess.start() is False
        assert sess.server_full is True
        await sess.close()
    finally:
        await srv.stop()


async def test_session_injoignable_marque_unreachable():
    sess = RemoteSTTSession(
        f"ws://127.0.0.1:{_free_port()}", on_partial=lambda t: None,
        on_final=lambda t, ms: None, open_timeout=1.0,
    )
    assert await sess.start() is False
    assert sess.unreachable is True
    await sess.close()


# ----------------------------------------------------------------------
# RemoteStreamingSTT (manager + fallback)
# ----------------------------------------------------------------------


class _FakeBatchSTT:
    """STT batch factice (fallback CPU local)."""

    def __init__(self, text="batch fallback"):
        self.text = text
        self.calls: list[bytes] = []
        self.warmed = False

    async def transcribe(self, pcm: bytes) -> str:
        self.calls.append(pcm)
        return self.text

    async def warmup(self) -> None:
        self.warmed = True


def _make_provider(url, fallback=None, **kw):
    prov = RemoteStreamingSTT(url, fallback=fallback or _FakeBatchSTT(), **kw)
    return prov


async def test_provider_une_session_par_locuteur(server):
    prov = _make_provider(server.url)
    prov.feed_sync("A", b"\x00" * 640)
    prov.feed_sync("B", b"\x00" * 640)
    await _wait_until(lambda: server.live_connections == 2)
    await prov.close_all()
    assert server.total_connections == 2


async def test_provider_final_distant_remonte_on_final(server):
    finals = []

    async def on_final(sid, text, ms):
        finals.append((sid, text))

    prov = _make_provider(server.url)
    prov.on_final = on_final
    prov.feed_sync("A", b"\x01" * 640)
    await _wait_until(lambda: server.live_connections == 1)
    prov.speech_end_sync("A", b"\x01" * 640)  # remote → flush
    await _wait_until(lambda: len(finals) == 1)
    await prov.close_all()
    assert finals[0] == ("A", "salut wally")


async def test_provider_partial_distant_remonte_on_partial(server):
    partials = []
    prov = _make_provider(server.url)
    prov.on_partial = lambda sid, text: partials.append((sid, text))
    prov.feed_sync("A", b"\x01" * 640)
    await _wait_until(lambda: server.live_connections == 1)
    prov.speech_end_sync("A", b"\x01" * 640)
    await _wait_until(lambda: ("A", "salut") in partials)
    await prov.close_all()
    assert ("A", "sa") in partials


async def test_provider_limite_locale_bascule_en_fallback(server):
    """Au-delà de max_connections, le nouveau locuteur passe sur le batch CPU local."""
    finals = []

    async def on_final(sid, text, ms):
        finals.append((sid, text))

    fallback = _FakeBatchSTT(text="depuis le batch")
    prov = _make_provider(server.url, fallback=fallback, max_connections=1)
    prov.on_final = on_final

    prov.feed_sync("A", b"\x01" * 640)             # prend l'unique slot distant
    await _wait_until(lambda: server.live_connections == 1)
    prov.feed_sync("B", b"\x02" * 640)             # plus de slot → fallback
    prov.speech_end_sync("B", b"\x02" * 640)       # batch transcrit le segment VAD

    await _wait_until(lambda: len(finals) == 1)
    await prov.close_all()
    assert finals[0] == ("B", "depuis le batch")
    assert fallback.calls  # le segment est bien passé au batch local
    assert server.total_connections == 1            # B n'a jamais ouvert de connexion distante


async def test_provider_injoignable_bascule_et_cache(server):
    finals = []

    async def on_final(sid, text, ms):
        finals.append((sid, text))

    fallback = _FakeBatchSTT(text="local")
    bad_url = f"ws://127.0.0.1:{_free_port()}"
    prov = _make_provider(bad_url, fallback=fallback, open_timeout=1.0, health_cache_s=30.0)
    prov.on_final = on_final

    prov.feed_sync("A", b"\x01" * 640)
    await _wait_until(lambda: prov._unreachable_until > 0, timeout=3.0)
    prov.speech_end_sync("A", b"\x01" * 640)
    await _wait_until(lambda: len(finals) == 1)
    await prov.close_all()

    assert finals[0] == ("A", "local")
    assert prov._unreachable_until > 0  # injoignable mis en cache


async def test_provider_session_perdue_en_cours_bascule_en_fallback(server):
    """Le PC GPU tombe en pleine conversation : la session établie meurt → on doit la
    retirer, armer le cache négatif et router le locuteur vers le batch local."""
    finals = []

    async def on_final(sid, text, ms):
        finals.append((sid, text))

    fallback = _FakeBatchSTT(text="repli local")
    prov = _make_provider(server.url, fallback=fallback, health_cache_s=30.0)
    prov.on_final = on_final

    prov.feed_sync("A", b"\x01" * 640)
    await _wait_until(lambda: "A" in prov._sessions and prov._sessions["A"].ready)

    # Coupure : le serveur distant disparaît.
    await server.stop()

    # La session morte est détectée et retirée ; le distant passe en cache « injoignable ».
    assert await _wait_until(lambda: "A" not in prov._sessions, timeout=3.0)
    assert prov._unreachable_until > 0

    # L'énoncé suivant est transcrit par le batch CPU local.
    prov.speech_end_sync("A", b"\x01" * 640)
    await _wait_until(lambda: len(finals) == 1)
    await prov.close_all()
    assert finals[0] == ("A", "repli local")
    assert fallback.calls


async def test_provider_session_inactive_est_fermee(server):
    prov = _make_provider(server.url, idle_timeout=0.05)
    prov.feed_sync("A", b"\x01" * 640)
    await _wait_until(lambda: server.live_connections == 1)

    task = asyncio.create_task(prov.maintain(interval=0.02))
    await _wait_until(lambda: server.live_connections == 0, timeout=2.0)
    task.cancel()
    await prov.close_all()
    assert "A" not in prov._sessions


async def test_provider_warmup_precharge_le_fallback(server):
    fallback = _FakeBatchSTT()
    prov = _make_provider(server.url, fallback=fallback)
    await prov.warmup()
    assert fallback.warmed is True


# ----------------------------------------------------------------------
# Backoff exponentiel quand le serveur reste injoignable
# ----------------------------------------------------------------------


class _UnreachableSession:
    """Session factice : la connexion échoue toujours (serveur injoignable)."""
    unreachable = True
    server_full = False

    async def start(self) -> bool:
        return False

    async def close(self) -> None:
        pass


class _OkSession:
    """Session factice : la connexion réussit."""
    unreachable = False
    server_full = False

    async def start(self) -> bool:
        return True

    async def close(self) -> None:
        pass


async def test_injoignable_backoff_exponentiel():
    clock = {"t": 100.0}
    prov = _make_provider("ws://x", now_fn=lambda: clock["t"], health_cache_s=30.0)

    await prov._open_and_watch("A", _UnreachableSession())
    assert prov._unreachable_until == 130.0   # 1er échec → cache de base (30s)
    await prov._open_and_watch("B", _UnreachableSession())
    assert prov._unreachable_until == 160.0   # 2e → ×2 (60s)
    await prov._open_and_watch("C", _UnreachableSession())
    assert prov._unreachable_until == 220.0   # 3e → ×4 (120s)


async def test_injoignable_backoff_plafonne():
    clock = {"t": 0.0}
    prov = _make_provider("ws://x", now_fn=lambda: clock["t"], health_cache_s=30.0)
    for _ in range(10):
        await prov._open_and_watch("S", _UnreachableSession())
    # Plafonné à health_cache_s × _BACKOFF_MAX_MULT (pas d'explosion).
    from bot.discord.voice.streaming import _BACKOFF_MAX_MULT
    assert prov._unreachable_until == 30.0 * _BACKOFF_MAX_MULT


async def test_succes_reinitialise_le_backoff():
    clock = {"t": 0.0}
    prov = _make_provider("ws://x", now_fn=lambda: clock["t"], health_cache_s=30.0)
    await prov._open_and_watch("A", _UnreachableSession())   # échec 1 → 30
    await prov._open_and_watch("B", _UnreachableSession())   # échec 2 → 60
    await prov._open_and_watch("C", _OkSession())            # serveur revenu → reset
    clock["t"] = 1000.0
    await prov._open_and_watch("D", _UnreachableSession())   # échec → repart du cache de base
    assert prov._unreachable_until == 1000.0 + 30.0


# ----------------------------------------------------------------------
# Construction (build_streaming_stt) + config
# ----------------------------------------------------------------------


def test_build_streaming_stt_construit_provider_et_fallback_whisper():
    from bot.config import VoiceConfig
    from bot.discord.voice.providers import FasterWhisperSTT, build_streaming_stt

    cfg = VoiceConfig(
        stt_provider="remote_stream",
        remote_stt_url="ws://10.0.0.1:9090",
        remote_stt_max_connections=2,
        remote_stt_fallback="faster_whisper",
    )
    prov = build_streaming_stt(cfg, phrases=["Wally"])
    assert isinstance(prov, RemoteStreamingSTT)
    assert prov._url == "ws://10.0.0.1:9090"
    assert prov._max_connections == 2
    assert isinstance(prov._fallback, FasterWhisperSTT)


def test_voice_config_defaut_remote_stt():
    from bot.config import VoiceConfig
    cfg = VoiceConfig()
    assert cfg.remote_stt_url.startswith("ws://")
    assert cfg.remote_stt_max_connections == 2
    assert cfg.remote_stt_fallback == "faster_whisper"
