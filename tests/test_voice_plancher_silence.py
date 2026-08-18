"""On ne paie plus le moteur STT pour du souffle.

Le VAD de webrtc tranche frame par frame, et un ventilateur, un clavier ou une
respiration lui suffisent : sur les 4 698 énoncés du repli local relevés dans
`/app/logs/2026-08-*/app.log`, **1 661 (35 %) reviennent VIDES du moteur**. Ce
n'est pas gratuit — pendant ce calcul, la vraie parole s'entasse, et
`_MAX_PENDING_FALLBACK` la jette (« voice: énoncé ABANDONNÉ — STT local
saturé »). Autrement dit : on perdait de la parole pour avoir transcrit du bruit.

Les deux valeurs du plancher sont MESURÉES, pas choisies. Sur ce même relevé :

    rms >= 100, durée >= 0,3 s : 0 perte / 3 037 · 1 183 vides écartés (71 %)
    rms >=  80, durée >= 0,3 s : 0 perte / 3 037 · 1 137 vides écartés (68 %)
    rms >= 200, durée >= 0,3 s : 18 pertes    · 1 303 vides écartés (78 %)

Le plus faible énoncé RÉELLEMENT transcrit est à rms 100, le plus court à
0,4 s. Le plancher est donc posé SOUS ces deux bords et non dessus : la marge
paie un micro plus faible ou un locuteur plus loin, pour un point de charge.

Ce que ces tests verrouillent, c'est le COMPORTEMENT — du souffle n'atteint pas
le moteur, de la parole l'atteint — jamais les constantes elles-mêmes : elles
doivent pouvoir être re-mesurées le jour où les micros changent.
"""
import array
import asyncio

import pytest

from bot.discord.voice.audio import SAMPLE_RATE, est_sous_le_plancher


def _pcm(secondes: float, amplitude: int) -> bytes:
    """Un segment PCM 16 kHz mono dont le rms vaut exactement `amplitude`."""
    return array.array("h", [amplitude] * int(SAMPLE_RATE * secondes)).tobytes()


# ----------------------------------------------------------------------
# La porte elle-même
# ----------------------------------------------------------------------

def test_le_silence_est_ecarte():
    jeter, _duree, niveau = est_sous_le_plancher(_pcm(1.0, 0))
    assert jeter
    assert niveau == 0


def test_le_souffle_est_ecarte():
    """Le cas le plus fréquent du relevé : 0,4 s à rms 30, rendu vide."""
    jeter, _duree, _niveau = est_sous_le_plancher(_pcm(0.4, 30))
    assert jeter


def test_le_hoquet_court_est_ecarte():
    """Trop court pour être un mot, même à plein volume."""
    jeter, duree, _niveau = est_sous_le_plancher(_pcm(0.1, 3000))
    assert jeter
    assert duree == pytest.approx(0.1)


def test_la_parole_passe():
    jeter, duree, niveau = est_sous_le_plancher(_pcm(1.5, 500))
    assert not jeter
    assert duree == pytest.approx(1.5)
    assert niveau == 500


def test_l_enonce_le_plus_faible_du_releve_passe():
    """rms 100 sur 0,6 s : le plus faible énoncé réellement transcrit en prod.
    S'il tombait, le plancher mangerait de la parole vécue."""
    jeter, _duree, _niveau = est_sous_le_plancher(_pcm(0.6, 100))
    assert not jeter


def test_l_enonce_le_plus_court_du_releve_passe():
    """0,4 s : le plus court énoncé réellement transcrit en prod."""
    jeter, _duree, _niveau = est_sous_le_plancher(_pcm(0.4, 310))
    assert not jeter


def test_une_mesure_impossible_laisse_passer():
    """Fail-open. On ne jette JAMAIS de la parole sur une panne de mesure : un
    segment de taille impaire fait échouer `audioop.rms`, et le doute doit
    profiter au locuteur."""
    segment = _pcm(1.0, 500) + b"\x00"  # taille impaire → rms illisible
    jeter, _duree, niveau = est_sous_le_plancher(segment)
    assert not jeter
    assert niveau == -1


# ----------------------------------------------------------------------
# Chemin 1 — le repli batch local (`RemoteStreamingSTT`)
# ----------------------------------------------------------------------

def _pipeline(monkeypatch):
    """Un `RemoteStreamingSTT` réduit à ce que `speech_end_sync` touche."""
    from bot.discord.voice.streaming import RemoteStreamingSTT

    p = RemoteStreamingSTT.__new__(RemoteStreamingSTT)
    p._sessions = {}
    p._fallback_speakers = set()
    p._pending_fallback = 0
    p._detached = set()
    p._ferme = False
    transcrits = []
    p._detach = lambda coro: (transcrits.append(coro), coro.close())
    return p, transcrits


def test_le_souffle_n_atteint_pas_le_moteur_local(monkeypatch):
    p, transcrits = _pipeline(monkeypatch)
    p.speech_end_sync("azrael", _pcm(0.4, 30))
    assert transcrits == []
    assert p._pending_fallback == 0  # la place reste libre pour la vraie parole


def test_la_parole_atteint_le_moteur_local(monkeypatch):
    p, transcrits = _pipeline(monkeypatch)
    p.speech_end_sync("azrael", _pcm(1.5, 500))
    assert len(transcrits) == 1
    assert p._pending_fallback == 1


def test_le_flush_distant_part_meme_sous_le_plancher(monkeypatch):
    """Le garde ne vaut QUE pour le moteur local. Côté distant, l'audio est déjà
    parti au fil de l'eau : ravaler le `flush` laisserait le serveur à attendre
    une fin d'énoncé qui ne viendrait jamais, et sa file monterait — le défaut
    même qu'on a corrigé le 2026-08-17."""
    p, _ = _pipeline(monkeypatch)

    class _Sess:
        ready = True

        def __init__(self):
            self.flushed = False

        def enqueue_flush(self):
            self.flushed = True

    sess = _Sess()
    p._sessions["azrael"] = sess
    p.speech_end_sync("azrael", _pcm(0.4, 30))
    assert sess.flushed


# ----------------------------------------------------------------------
# Chemin 2 — le mode batch pur (`VoiceService._on_segment`)
# ----------------------------------------------------------------------

def _service():
    """Un `VoiceService` réduit à ce que `_on_segment` touche."""
    from bot.discord.voice.service import VoiceService

    s = VoiceService.__new__(VoiceService)
    appels = []

    class _Stt:
        async def transcribe(self, pcm):
            appels.append(pcm)
            return "salut"

    class _Quota:
        def __init__(self):
            self.secondes = 0.0

        def add_stt_seconds(self, s):
            self.secondes += s

    s._stt = _Stt()
    s.quota = _Quota()
    s._dispatch_transcript = lambda *a, **k: asyncio.sleep(0)
    return s, appels


def test_le_souffle_n_atteint_pas_le_moteur_batch():
    """Le second point d'entrée du moteur. Poser la porte sur un seul des deux
    chemins l'aurait laissée ouverte dès que la config bascule en batch pur."""
    s, appels = _service()
    asyncio.run(s._on_segment(object(), _pcm(0.4, 30)))
    assert appels == []
    assert s.quota.secondes == 0.0  # pas de quota brûlé non plus


def test_la_parole_atteint_le_moteur_batch():
    s, appels = _service()
    asyncio.run(s._on_segment(object(), _pcm(1.5, 500)))
    assert len(appels) == 1
    assert s.quota.secondes == pytest.approx(1.5)
