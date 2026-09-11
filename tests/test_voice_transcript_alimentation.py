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


# ── Ce qui survit au live : le journal ───────────────────────────────────────

class _ConvLog:
    """Juste l'API `log()` de `ConversationLogger`, qui enregistre ce qu'on lui remet."""

    def __init__(self):
        self.events: list[tuple[str, str, str, dict]] = []

    def log(self, platform, channel, event_type, /, **fields):
        self.events.append((platform, channel, event_type, fields))


@pytest.fixture
def journal_log() -> _ConvLog:
    return _ConvLog()


@pytest.fixture
def feed_journalise(journal_log) -> VoiceTranscriptFeed:
    f = VoiceTranscriptFeed(conv_log=journal_log)
    f.activate()
    f.open_broadcast(SALON)
    return f


def test_le_chemin_du_live_journalise_ce_qu_il_entend(feed_journalise, journal_log):
    """En live, Wally est en ÉCOUTE : c'est `_observe_transcript`, pas
    `_remember_line`, qui voit passer la parole. Le journal doit être nourri là."""
    svc = types.SimpleNamespace(
        _bot=types.SimpleNamespace(tally=None, overlay_narrator=None),
        channel_id=SALON, channel_name="STREAM", _listen_tasks=set(),
        _current_speaker_id="111",
    )
    VoiceService._observe_transcript(svc, "Azraël (@azrael)", "la clé est là  mais je peux pas")

    assert journal_log.events == [(
        vt.JOURNAL_PLATFORM, "STREAM", vt.JOURNAL_EVENT,
        {"author": "Azraël (@azrael)", "content": "la clé est là mais je peux pas"},
    )]


def test_le_chemin_du_live_publie_ce_qu_il_entend_au_panneau_vocal(feed):
    """Le panneau Vocal du dashboard est resté vide douze jours : seul le chemin
    de CONVERSATION publiait, et en live Wally n'est qu'en écoute."""
    from bot.discord.voice.feed import VoiceFeed

    panneau = VoiceFeed()
    svc = types.SimpleNamespace(
        _bot=types.SimpleNamespace(tally=None, overlay_narrator=None, voice_feed=panneau),
        channel_id=SALON, channel_name="STREAM", _listen_tasks=set(),
        _current_speaker_id="111",
    )
    VoiceService._observe_transcript(svc, "Azraël (@azrael)", "on repart", stt_ms=812.4)

    assert panneau.snapshot() == [{
        "type": "heard", "channel_id": str(SALON), "channel_name": "STREAM",
        "speaker": "Azraël (@azrael)", "speaker_id": "111", "text": "on repart",
        "stt_ms": 812,
    }]


def test_la_parole_hors_diffusion_n_entre_pas_au_journal(feed_journalise, journal_log):
    assert not feed_journalise.record(9999, "Bob", "un truc entre nous", channel_name="privé")
    assert journal_log.events == []


def test_la_parole_hors_live_n_entre_pas_au_journal(feed_journalise, journal_log, monkeypatch):
    monkeypatch.setattr(vt, "current_stream_status", lambda: {"live": False})
    assert not feed_journalise.record(SALON, "Azraël", "le live est coupé", channel_name="STREAM")
    assert journal_log.events == []


def test_sa_propre_replique_est_signee_de_son_nom_au_journal(feed_journalise, journal_log):
    """« Toi » sert au prompt ; au journal, une recherche par auteur doit le retrouver."""
    svc = types.SimpleNamespace(
        history=[], channel_id=SALON, channel_name="STREAM",
        _bot=types.SimpleNamespace(config=types.SimpleNamespace(
            bot=types.SimpleNamespace(name="Wally"))),
    )
    _remember_line(svc, role="assistant", speaker=_SELF_LABEL, text="vous allez vous faire fumer")

    assert f"[{_SELF_LABEL}] vous allez vous faire fumer" in feed_journalise.render()
    assert journal_log.events[0][3] == {"author": "Wally", "content": "vous allez vous faire fumer"}
