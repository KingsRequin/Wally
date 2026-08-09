"""Le flux du stream doit affirmer une PERCEPTION, pas la nier.

Le bloc se terminait par « Tu n'as RIEN à en faire : tu ne commentes pas, tu ne
réagis pas, tu n'en parles pas de toi-même. » Wally en a conclu qu'il ne percevait
rien, et a redemandé le 2026-08-09 une capacité qu'il possédait depuis le 05.

Or cette moitié de consigne ne protège de rien : l'initiative est bloquée
MÉCANIQUEMENT en amont — `spontaneous_channel_speak_enabled: false` fait jeter tout
SPEAK spontané dans `cognitive_loop`, le flux n'appelle aucun `notify_*` donc ne
réveille pas la cadence, et la parole spontanée est de toute façon redirigée vers
son salon dédié.

Ce qu'elle protège vraiment, c'est la DIGRESSION dans une réponse : une réponse à
une mention ne passe pas par `cognitive_loop` mais par les handlers, et le bloc est
dans son prompt système à ce moment-là. Rien n'empêche un « au fait, le chat
d'Azraël dit que… » greffé sur une question sans rapport. C'est cette moitié — et
elle seule — qu'il faut garder.
"""
from bot.core.stream_feed import StreamFeed


def _bloc() -> str:
    feed = StreamFeed(streamer_name="Azraël")
    feed.record("Azraël lance son live sur Apex Legends", kind="live_start")
    feed.record_chat("bob", "gg les gars")
    return feed.render()


def test_le_bloc_affirme_quil_percoit():
    bloc = _bloc()
    assert "perçois" in bloc, (
        f"le bloc ne dit nulle part qu'il PERÇOIT le live :\n{bloc}"
    )


def test_le_bloc_nannule_plus_la_perception():
    """« RIEN à en faire » est redondant (verrou mécanique) ET trompeur."""
    bloc = _bloc()
    assert "RIEN à en faire" not in bloc
    assert "tu ne réagis pas" not in bloc


def test_le_bloc_garde_le_garde_fou_anti_digression():
    """La seule moitié de la consigne qui travaille encore."""
    bloc = _bloc()
    assert "n'ouvres pas" in bloc, (
        f"plus rien ne l'empêche de greffer le live sur une réponse :\n{bloc}"
    )


def test_le_bloc_reste_absent_sans_rien_de_frais():
    assert StreamFeed(streamer_name="Azraël").render() == ""
