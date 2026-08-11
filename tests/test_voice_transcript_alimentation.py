# tests/test_voice_transcript_alimentation.py
"""Le fil vocal et le tampon de contexte écrit sont nourris au MÊME endroit.

Deux appelants séparés finissent toujours par diverger : c'est le jour où un
troisième chemin de parole apparaît que l'un des deux tampons l'oublie.
"""
import types

import pytest

import bot.core.voice_transcript as vt
from bot.core.voice_transcript import VoiceTranscriptFeed
from bot.discord.voice.brain import _HISTORY_MAX, _SELF_LABEL, _remember_line
from bot.discord.voice.service import VoiceService

SALON = 4242


@pytest.fixture(autouse=True)
def _reset_active():
    vt._active = None
    yield
    vt._active = None


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    monkeypatch.setattr(vt, "current_stream_status", lambda: {"live": True})


@pytest.fixture
def feed() -> VoiceTranscriptFeed:
    f = VoiceTranscriptFeed()
    f.activate()
    f.open_broadcast(SALON)
    return f


def _service(channel_id=SALON):
    return types.SimpleNamespace(history=[], channel_id=channel_id)


def test_une_parole_entendue_va_dans_les_deux_tampons(feed):
    svc = _service()
    _remember_line(svc, role="user", speaker="Azraël", text="on repart sur Storm Point")

    assert svc.history == [{"role": "user", "content": "Azraël: on repart sur Storm Point"}]
    assert "[Azraël] on repart sur Storm Point" in feed.render()


def test_la_reponse_de_wally_est_consignee_a_la_deuxieme_personne(feed):
    svc = _service()
    _remember_line(svc, role="assistant", speaker=_SELF_LABEL, text="vous allez vous faire fumer")

    # Le fil LLM garde la réponse nue (c'est déjà « lui » qui parle)…
    assert svc.history == [{"role": "assistant", "content": "vous allez vous faire fumer"}]
    # …et le bloc de contexte la nomme, pour qu'il se relise dans la conversation.
    assert f"[{_SELF_LABEL}] vous allez vous faire fumer" in feed.render()


def test_le_fil_vocal_reste_borne(feed):
    svc = _service()
    for i in range(_HISTORY_MAX + 5):
        _remember_line(svc, role="user", speaker="Azraël", text=f"phrase {i}")
    assert len(svc.history) == _HISTORY_MAX


def test_le_fil_vocal_est_ecrit_meme_sans_tampon_actif():
    """Le contexte écrit est un confort ; le vocal, lui, ne doit jamais s'arrêter."""
    svc = _service()
    _remember_line(svc, role="user", speaker="Azraël", text="on repart")
    assert svc.history == [{"role": "user", "content": "Azraël: on repart"}]


def test_un_tampon_en_erreur_ne_casse_pas_le_vocal(feed, monkeypatch):
    def _boum(*a, **k):
        raise RuntimeError("tampon cassé")

    monkeypatch.setattr(feed, "record", _boum)
    svc = _service()
    _remember_line(svc, role="user", speaker="Azraël", text="on repart")
    assert svc.history == [{"role": "user", "content": "Azraël: on repart"}]


def test_la_parole_d_un_autre_salon_n_entre_pas_dans_le_contexte(feed):
    """Wally déplacé hors du salon diffusé : le fil vocal continue, pas le contexte."""
    svc = _service(channel_id=9999)
    _remember_line(svc, role="user", speaker="Bob", text="un truc entre nous")
    assert len(svc.history) == 1
    assert feed.render() == ""


# ── Déplacement de salon ─────────────────────────────────────────────────────

class _ServicePourDeplacement:
    """Juste ce qu'il faut de `VoiceService` pour exercer `follow_move`."""

    listen_only = False
    _channel = None
    follow_move = VoiceService.follow_move
    _forget_transcript = VoiceService._forget_transcript


def test_un_deplacement_de_salon_oublie_ce_qui_a_ete_entendu(feed):
    feed.record(SALON, "Azraël", "on repart sur Storm Point")
    _ServicePourDeplacement().follow_move(types.SimpleNamespace(id=9999))
    assert feed.render() == ""
