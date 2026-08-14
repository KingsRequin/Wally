"""Les places du STT distant vont d'abord à ceux à qui Wally doit répondre.

Vécu en direct le 2026-08-14. Le serveur de transcription (le PC du créateur)
ne tient que deux locuteurs — une limite de VRAM, pas un réglage. Ils étaient
quatre en vocal ce soir-là, et l'attribution se faisait au premier qui ouvrait
la bouche :

    22:49:39  serveur plein → 419172225451556874 en local     ← Azraël, le streamer
    23:11:35  session 419172225451556874 perdue → fallback batch 30s

Les deux places sont restées aux deux invités, qui les rouvraient et refermaient
en boucle. Azraël est passé sur le Whisper local, par lots de trente secondes :
ses phrases revenaient en « Biri birip » et « Sous-titrage ST' 501 », le mot
« Wally » se perdait dedans, et ses demandes n'atteignaient plus personne. Une
heure durant, jusqu'à ce qu'il demande lui-même « Allo Wally t'es là ? ».

Qui est prioritaire n'est pas écrit en dur : `voice.requesters` porte déjà, dans
la config, ceux au nom de qui Wally agit (le créateur et le streamer).
"""
from unittest.mock import MagicMock, patch

import pytest

from bot.discord.voice.streaming import RemoteStreamingSTT

AZRAEL = "419172225451556874"     # streamer — dans `voice.requesters`
REQUIN = "610550333042589752"     # créateur — dans `voice.requesters`
XEFORCE = "432140002109947904"    # invité
TAKI = "528237220327325720"       # invité


@pytest.fixture(autouse=True)
def _pas_de_taches(monkeypatch):
    """Les tâches détachées ne sont pas le sujet : on observe l'aiguillage."""
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())


def _manager(occupees=(), *, prioritaires=(AZRAEL, REQUIN), places=2):
    mgr = RemoteStreamingSTT(
        "ws://stt.test",
        fallback=MagicMock(),
        max_connections=places,
        session_factory=lambda sid: MagicMock(name=f"sess:{sid}", ready=True),
        priority_speakers=set(prioritaires),
    )
    for sid in occupees:
        mgr._sessions[sid] = MagicMock(name=f"sess:{sid}", ready=True)
    return mgr


def test_le_streamer_prend_la_place_d_un_invite_quand_c_est_plein():
    """Le cas du 2026-08-14 : deux invités tiennent les deux places."""
    mgr = _manager(occupees=(XEFORCE, TAKI))

    mgr.feed_sync(AZRAEL, b"audio")

    assert AZRAEL in mgr._sessions, "le streamer doit obtenir une place"
    assert AZRAEL not in mgr._fallback_speakers
    restants = [s for s in (XEFORCE, TAKI) if s in mgr._sessions]
    assert len(restants) == 1, "une seule place cédée, pas les deux"
    assert len(mgr._sessions) <= 2


def test_l_invite_delogé_repasse_en_local_sans_perdre_sa_parole():
    mgr = _manager(occupees=(XEFORCE, TAKI))

    mgr.feed_sync(AZRAEL, b"audio")

    delogé = next(s for s in (XEFORCE, TAKI) if s not in mgr._sessions)
    assert delogé in mgr._fallback_speakers, (
        "le délogé doit être routé vers le repli local, pas laissé sans voie"
    )


def test_un_invite_ne_deloge_pas_le_streamer():
    """La priorité n'est pas réciproque, sinon ce n'en serait pas une."""
    mgr = _manager(occupees=(AZRAEL, REQUIN))

    mgr.feed_sync(XEFORCE, b"audio")

    assert AZRAEL in mgr._sessions and REQUIN in mgr._sessions
    assert XEFORCE in mgr._fallback_speakers


def test_un_prioritaire_ne_deloge_pas_un_autre_prioritaire():
    """Entre eux, premier arrivé premier servi : personne à départager."""
    mgr = _manager(occupees=(REQUIN, XEFORCE), prioritaires=(AZRAEL, REQUIN))

    mgr.feed_sync(AZRAEL, b"audio")

    assert REQUIN in mgr._sessions, "le créateur garde sa place"
    assert XEFORCE not in mgr._sessions, "c'est l'invité qui cède"
    assert AZRAEL in mgr._sessions


def test_serveur_injoignable_personne_ne_deloge_personne():
    """Libérer une place n'aide pas quand c'est le serveur qui ne répond pas —
    et l'invité perdrait sa session pour rien."""
    mgr = _manager(occupees=(XEFORCE, TAKI))
    mgr._unreachable_until = mgr._now() + 60

    mgr.feed_sync(AZRAEL, b"audio")

    assert AZRAEL in mgr._fallback_speakers
    assert XEFORCE in mgr._sessions and TAKI in mgr._sessions


def test_sans_liste_de_prioritaires_le_comportement_ne_change_pas():
    mgr = _manager(occupees=(XEFORCE, TAKI), prioritaires=())

    mgr.feed_sync(AZRAEL, b"audio")

    assert AZRAEL in mgr._fallback_speakers
    assert len(mgr._sessions) == 2


def test_une_place_libre_ne_deloge_personne():
    mgr = _manager(occupees=(XEFORCE,))

    mgr.feed_sync(AZRAEL, b"audio")

    assert XEFORCE in mgr._sessions and AZRAEL in mgr._sessions


# ── Une session perdue n'est pas un serveur mort ──

def test_une_session_perdue_ne_penalise_pas_les_autres_locuteurs():
    """`_on_session_lost` armait le backoff « injoignable » (30 → 60 → 120 s)
    pour TOUT LE MONDE. Le 2026-08-14, le serveur répondait pourtant aux deux
    autres locuteurs au même instant : Azraël était exclu du distant sans
    qu'aucun serveur ne soit tombé."""
    mgr = _manager(occupees=(AZRAEL, XEFORCE))

    mgr._on_session_lost(AZRAEL)

    assert mgr._unreachable_until == 0.0, "le serveur vit : pas de backoff global"
    assert mgr._remote_allowed(mgr._now()) is True


def test_la_derniere_session_perdue_arme_bien_le_backoff():
    """Plus personne dessus : là, le serveur est peut-être vraiment tombé, et
    retenter à chaque énoncé coûte `open_timeout` de latence sur la parole."""
    mgr = _manager(occupees=(AZRAEL,))

    mgr._on_session_lost(AZRAEL)

    assert mgr._unreachable_until > mgr._now()


# ── Câblage depuis la config ──

def test_les_prioritaires_viennent_de_voice_requesters():
    """La liste n'est pas écrite en dur : `voice.requesters` porte déjà ceux au
    nom de qui Wally agit (Apex, duels). Un requester ajouté demain devient
    prioritaire sans une ligne de code."""
    from bot.config import VoiceConfig
    from bot.discord.voice.providers import build_streaming_stt

    cfg = VoiceConfig()
    cfg.stt_provider = "remote_stream"
    cfg.remote_stt_fallback = "faster_whisper"
    cfg.requesters = [
        {"discord_id": REQUIN, "twitch_login": "kingsrequin"},
        {"discord_id": AZRAEL, "twitch_login": "azrael_ttv"},
        {"twitch_login": "sans_discord"},          # entrée incomplète : ignorée
    ]

    with patch("bot.discord.voice.providers._build_batch_stt", return_value=MagicMock()):
        mgr = build_streaming_stt(cfg)

    assert mgr._priority_speakers == {REQUIN, AZRAEL}
