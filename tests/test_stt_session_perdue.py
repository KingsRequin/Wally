"""Serveur STT distant mort : la parole ne doit jamais se perdre.

`feed_sync` enregistre la session AVANT de savoir si elle s'ouvre. Quand le
serveur est injoignable, l'énoncé partait dans une session qui n'aboutirait
jamais, et `_open_and_watch` la retirait sans transcrire ce qu'elle contenait :
5 à 35 s d'attente, puis une parole perdue.
"""
import array
from unittest.mock import MagicMock

from bot.discord.voice.streaming import RemoteStreamingSTT

# Un énoncé plausible — 1 s à rms 500. Ces tests portaient un marqueur
# symbolique (`b"audio"`, soit 0,0 s) ; depuis que le repli local écarte ce qui
# est trop court pour être de la parole, un tel marqueur n'atteint plus le
# moteur, et `test_la_file_locale_est_bornee` passait pour la MAUVAISE raison :
# il vérifiait que rien n'est transcrit, ce que le plancher rendait vrai sans
# que la borne de file soit pour autant testée.
_ENONCE = array.array("h", [500] * 16000).tobytes()


def _manager():
    mgr = RemoteStreamingSTT.__new__(RemoteStreamingSTT)
    mgr._sessions = {}
    mgr._fallback_speakers = set()
    mgr._pending_fallback = 0
    # Références fortes des tâches détachées : sans elles la boucle asyncio ne
    # retient qu'une référence faible, et un énoncé peut être collecté en vol.
    mgr._detached = set()
    mgr._transcribed = []
    # On observe l'aiguillage, pas la transcription elle-même.
    mgr._fallback_transcribe = lambda sid, seg: mgr._transcribed.append((sid, seg))
    return mgr


def test_une_session_non_prete_ne_capte_pas_l_enonce(monkeypatch):
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())

    mgr = _manager()
    sess = MagicMock()
    sess.ready = False               # ouverture en cours, ou vouée à l'échec
    mgr._sessions["u1"] = sess

    mgr.speech_end_sync("u1", _ENONCE)

    sess.enqueue_flush.assert_not_called()
    assert mgr._transcribed == [("u1", _ENONCE)], "l'énoncé doit partir en local"


def test_une_session_prete_recoit_bien_le_flush(monkeypatch):
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())

    mgr = _manager()
    sess = MagicMock()
    sess.ready = True
    mgr._sessions["u1"] = sess

    mgr.speech_end_sync("u1", _ENONCE)

    sess.enqueue_flush.assert_called_once()
    assert mgr._transcribed == [], "pas de double transcription"


def test_sans_session_l_enonce_part_en_local(monkeypatch):
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())

    mgr = _manager()
    mgr.speech_end_sync("u1", _ENONCE)
    assert mgr._transcribed == [("u1", _ENONCE)]


def test_la_file_locale_est_bornee(monkeypatch):
    """Mesuré en live : à trois locuteurs, la file montait à 35 s de retard.
    À ce décalage, Wally réagit à une phrase que tout le monde a oubliée."""
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())

    mgr = _manager()
    mgr._pending_fallback = mod._MAX_PENDING_FALLBACK
    mgr.speech_end_sync("u1", _ENONCE)
    assert mgr._transcribed == [], "l'énoncé de trop doit être abandonné, pas empilé"


def test_un_enonce_passe_quand_la_file_respire(monkeypatch):
    import bot.discord.voice.streaming as mod
    monkeypatch.setattr(mod.asyncio, "create_task", lambda coro: MagicMock())

    mgr = _manager()
    mgr.speech_end_sync("u1", _ENONCE)
    assert mgr._transcribed == [("u1", _ENONCE)]
    assert mgr._pending_fallback == 1
