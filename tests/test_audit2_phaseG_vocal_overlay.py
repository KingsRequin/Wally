# tests/test_audit2_phaseG_vocal_overlay.py
"""Phase G du second audit : vocal et overlay.

A2-leave — `close_all()` était appelé AVANT `stop_listening()` : le thread audio
           rouvrait une session sur le pipeline qu'on venait de fermer.
A2-tts   — un TTS qui lève sautait `await done.wait()` → anti-larsen désarmé
           pendant que le tampon PCM finissait de jouer.
A2-test  — `force_live(0)` ne remettait pas `_was_live` : le vrai live suivant
           héritait de l'état du mode test, pendu ouvert compris.
A2-join  — `_channel` posé avant `connect()` : salon fantôme si ça échoue.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock


# ────────────────────────────── A2-leave ──────────────────────────────
def test_l_ecoute_est_coupee_avant_la_fermeture_du_stt():
    from bot.discord.voice.service import VoiceService

    src = inspect.getsource(VoiceService.leave)
    # Les formes EXÉCUTABLES : les commentaires citent les deux appels.
    assert (src.index("self._vc.stop_listening()")
            < src.index("await self._streaming.close_all()"))


@pytest.mark.asyncio
async def test_un_pipeline_ferme_ne_rouvre_plus_de_session():
    from bot.discord.voice.streaming import RemoteStreamingSTT

    p = RemoteStreamingSTT.__new__(RemoteStreamingSTT)
    p._ferme = True
    p._now = lambda: 0.0
    p._last_activity = {}
    p._fallback_speakers = set()
    p._priority_speakers = set()   # aucun prioritaire : l'aiguillage par profil n'est pas le sujet ici
    p._sessions = {}

    p.feed_sync("A", b"\x00" * 640)          # ne doit rien tenter
    assert p._sessions == {}
    assert p._last_activity == {}, "le pipeline fermé a quand même enregistré"


def test_le_pipeline_se_rouvre_au_join_suivant():
    """`join()` RÉUTILISE le même objet : sans réouverture, le STT serait mort
    dès le premier `leave()`."""
    from bot.discord.voice.streaming import RemoteStreamingSTT

    src = inspect.getsource(RemoteStreamingSTT.maintain)
    assert "self._ferme = False" in src


def test_le_backoff_injoignable_survit_a_un_leave():
    """Il ne doit PAS être effacé : sinon on re-teste un serveur mort à chaque
    join. Un changement de config reconstruit l'objet de toute façon."""
    from bot.discord.voice.streaming import RemoteStreamingSTT

    src = inspect.getsource(RemoteStreamingSTT.close_all)
    assert "self._unreachable_until = 0.0" not in src
    assert "self._detached.clear()" in src


# ────────────────────────────── A2-tts ──────────────────────────────
def test_l_attente_de_fin_de_lecture_est_dans_le_finally():
    from bot.discord.voice.service import VoiceService

    src = inspect.getsource(VoiceService._speak_streaming)
    i_finally = src.index("finally:")
    assert src.index("await done.wait()") > i_finally, "anti-larsen désarmé sur erreur TTS"


# ────────────────────────────── A2-test ──────────────────────────────
def _narrateur():
    from bot.intelligence.overlay_narrator import OverlayNarrator

    n = OverlayNarrator.__new__(OverlayNarrator)
    n._force_until = 100.0
    n._force_epoch = 100.0
    n._was_live = True
    return n


def test_couper_le_mode_test_reouvre_la_transition():
    n = _narrateur()
    assert n.force_live(0) == 0.0
    assert n._was_live is False, "le vrai live suivant hérite de l'état du réglage"


def test_activer_le_mode_test_ne_touche_pas_au_drapeau():
    n = _narrateur()
    n._was_live = False
    n.force_live(10)
    assert n._was_live is False


# ────────────────────────────── A2-join ──────────────────────────────
def test_l_etat_du_salon_n_est_engage_qu_apres_la_connexion():
    from bot.discord.voice.service import VoiceService

    src = inspect.getsource(VoiceService._join_locked)
    i_connect = src.index("await channel.connect(")
    i_channel = src.index("self._channel = channel")
    assert i_connect < i_channel, "salon renseigné avant que la connexion réussisse"


@pytest.mark.asyncio
async def test_une_connexion_ratee_ne_laisse_pas_de_salon_fantome():
    from bot.discord.voice.service import VoiceService

    s = VoiceService.__new__(VoiceService)
    s._vc = None
    s._channel = None
    s._pending_inviter = None
    s.listen_only = False
    s.listen_optout = False
    s._cfg = MagicMock()

    salon = MagicMock()
    salon.connect = AsyncMock(side_effect=RuntimeError("4006"))

    with pytest.raises(RuntimeError):
        await VoiceService._join_locked(s, salon, None, False)

    assert s._channel is None, "salon fantôme : /status citerait un salon inexistant"
    assert s._vc is None
