# tests/test_overlay_raid.py
"""L'accueil d'un raid à l'écran.

Un raid alimentait déjà l'émotion et le flux du stream, mais ne se voyait NULLE
PART : quarante personnes arrivaient d'un coup et l'overlay ne bronchait pas.
C'est pourtant le moment le plus fort d'un live, et celui qui mérite le plus
qu'on remercie quelqu'un par son nom.
"""
import time
from unittest.mock import AsyncMock, MagicMock

from bot.core.overlay_feed import OverlayFeed
from bot.intelligence.overlay_narrator import OverlayNarrator


def _narrateur(live=True):
    n = OverlayNarrator(OverlayFeed(), AsyncMock(), lambda: live)
    n._feed = MagicMock()
    return n


def _publie(n):
    return n._feed.widget.call_args


def test_un_raid_remercie_par_le_nom():
    n = _narrateur()
    assert n.celebrate_raid("Azrael_ttv", 42) is True

    args, kwargs = _publie(n)
    assert args[0] == "raid"
    assert kwargs["raider"] == "Azrael_ttv"
    assert kwargs["viewers"] == 42


def test_il_reste_une_dizaine_de_secondes():
    """La règle de l'overlay : une info s'affiche ~10 s, sauf jeu en cours."""
    n = _narrateur()
    n.celebrate_raid("Azra", 10)
    assert _publie(n).kwargs["duration"] == 10


def test_rien_hors_live():
    n = _narrateur(live=False)
    assert n.celebrate_raid("Azra", 10) is False
    n._feed.widget.assert_not_called()


def test_un_raid_n_est_jamais_rationne():
    """`_may_react` espace les événements pour ne pas saturer l'écran. Un raid
    est trop rare pour tomber dans ce filet : il arrive quand il arrive, et
    passer à côté vaut bien pire qu'un widget de trop."""
    n = _narrateur()
    n._last_event_at = time.monotonic()      # un événement vient JUSTE de passer
    assert n._may_react() is False           # tout le reste serait refusé
    assert n.celebrate_raid("Azra", 10) is True


def test_un_nom_a_rallonge_est_borne():
    """Il s'affiche en grand : un pseudo de 200 caractères casserait la carte."""
    n = _narrateur()
    n.celebrate_raid("A" * 200, 10)
    assert len(_publie(n).kwargs["raider"]) <= 24


def test_un_compte_absurde_ne_passe_pas():
    """`viewer_count` vient de Twitch : on ne lui fait pas confiance aveuglément."""
    n = _narrateur()
    n.celebrate_raid("Azra", -5)
    assert _publie(n).kwargs["viewers"] == 0


def test_un_raid_sans_nom_reste_affichable():
    """Mieux vaut « on se fait raid » que pas de célébration du tout."""
    n = _narrateur()
    assert n.celebrate_raid("", 30) is True
    assert _publie(n).kwargs["viewers"] == 30


# ── le câblage Twitch ────────────────────────────────────────────────────────


def _bot_avec_narrateur(raid_actif=True):
    """Un bot Twitch minimal, avec un narrateur d'overlay branché derrière."""
    from types import SimpleNamespace

    narrateur = MagicMock()
    bot = MagicMock()
    bot.discord_bot = SimpleNamespace(overlay_narrator=narrateur)
    bot.config.twitch_events.get = lambda k, d=None: (
        MagicMock(active=True, message="raid {username}") if raid_actif else None
    )
    bot.emotion.get_state = MagicMock(return_value={})
    return bot, narrateur


def test_le_raid_est_celebre_meme_sans_message_automatique():
    """LE piège du 2026-08-07 : le handler sortait avant d'alimenter le flux dès
    que le message auto était coupé, et le raid passait inaperçu. La célébration
    à l'écran ne dépend pas davantage de ce réglage."""
    from bot.twitch.events.social import _celebrate_raid

    bot, narrateur = _bot_avec_narrateur(raid_actif=False)
    _celebrate_raid(bot, "Azrael_ttv", 42)
    narrateur.celebrate_raid.assert_called_once_with("Azrael_ttv", 42)


def test_un_narrateur_absent_ne_casse_rien():
    """Discord peut ne pas être branché : le remerciement du chat doit passer."""
    from types import SimpleNamespace

    from bot.twitch.events.social import _celebrate_raid

    bot = MagicMock()
    bot.discord_bot = SimpleNamespace(overlay_narrator=None)
    _celebrate_raid(bot, "Azra", 10)      # ne lève pas


def test_un_overlay_en_erreur_ne_bloque_pas_le_raid():
    from bot.twitch.events.social import _celebrate_raid

    bot, narrateur = _bot_avec_narrateur()
    narrateur.celebrate_raid.side_effect = RuntimeError("feed mort")
    _celebrate_raid(bot, "Azra", 10)      # avalé, journalisé
