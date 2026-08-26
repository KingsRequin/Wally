"""Une phrase transcrite ne doit pas disparaître parce que le locuteur a bougé.

`_on_stream_final` jetait la transcription dès que le locuteur n'était plus dans
le suivi de flux — une reconnexion pendant la transcription suffit. La phrase
n'entrait alors ni au fil vocal, ni au tampon de contexte écrit, et la seule
trace était un `logger.debug` : niveau qui n'existe pas en prod, d'où ZÉRO
occurrence dans tous les journaux du dépôt pour un cas décrit comme vécu.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.discord.voice.service import VoiceService


def make_service(membres=()):
    """Un service vocal réduit à ce que ce chemin touche."""
    sf = VoiceService.__new__(VoiceService)
    sf._stream_users = {}
    sf._channel = SimpleNamespace(members=list(membres), id=42)
    sf._dispatch_transcript = AsyncMock()
    return sf


def make_membre(uid: int, nom: str = "Azraël"):
    return SimpleNamespace(id=uid, name=nom.lower(), display_name=nom, bot=False)


async def test_le_locuteur_suivi_recoit_sa_phrase():
    sf = make_service()
    membre = make_membre(123)
    sf._stream_users["123"] = membre

    await sf._on_stream_final("123", "salut tout le monde", 12.0)

    sf._dispatch_transcript.assert_awaited_once_with(membre, "salut tout le monde", 12.0)


async def test_un_locuteur_perdu_du_suivi_est_retrouve_dans_le_salon():
    """Le cas qui faisait disparaître la phrase : plus dans `_stream_users`,
    mais toujours dans le salon — son id suffit à le nommer."""
    membre = make_membre(123)
    sf = make_service([membre])

    await sf._on_stream_final("123", "vous m'entendez ?", 8.0)

    sf._dispatch_transcript.assert_awaited_once_with(membre, "vous m'entendez ?", 8.0)


async def test_une_phrase_vraiment_orpheline_est_signalee_pas_avalee():
    """Parti du salon pour de bon : la phrase se perd, mais bruyamment."""
    sf = make_service([make_membre(999)])

    await sf._on_stream_final("123", "je m'en vais", 8.0)

    sf._dispatch_transcript.assert_not_awaited()


async def test_sans_salon_la_recherche_ne_leve_pas():
    sf = make_service()
    sf._channel = None

    await sf._on_stream_final("123", "personne n'écoute", 8.0)

    sf._dispatch_transcript.assert_not_awaited()


async def test_un_identifiant_qui_n_est_pas_un_nombre_ne_leve_pas():
    sf = make_service([make_membre(123)])

    await sf._on_stream_final("pas-un-id", "bruit", 8.0)

    sf._dispatch_transcript.assert_not_awaited()


def test_le_membre_est_retrouve_par_son_identifiant_discord():
    autre, cible = make_membre(111, "Taki"), make_membre(222, "Malef")
    sf = make_service([autre, cible])

    assert sf._membre_du_salon("222") is cible
    assert sf._membre_du_salon("333") is None
