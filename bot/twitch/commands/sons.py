# bot/twitch/commands/sons.py
"""Les sons que le chat déclenche — `!apero`, `!perks`, `!bonjour`…

Reprend la fonctionnalité la plus utilisée de PhantomBot : comptés dans ses logs
de chat sur 7 mois, les sept sons totalisent **232 usages**, plus que tout le
reste réuni. Rien n'est écrit en dur ici : le dossier `data/sons/commande/` est
relu à chaque message, et un fichier déposé pendant le live devient une commande
immédiatement — `APERO.mp3` répond à `!apero`.

**Le cooldown appartient au SERVEUR**, comme celui des popups virus. Côté page,
il suffirait d'ouvrir un second overlay pour le contourner ; et il n'y a pas
qu'un client (OBS, l'aperçu du panneau, un navigateur ouvert).

Aucun cooldown par défaut (arbitrage owner du 2026-08-28) : PhantomBot imposait
120 s à tous, ce que personne n'avait demandé. Chaque son porte le sien.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# {nom de commande → instant du dernier déclenchement}. En RAM : un redémarrage
# remet les compteurs à zéro, et c'est sans conséquence — le pire cas est un son
# rejoué une fois de trop après un rebuild.
_derniers: dict[str, float] = {}


def _atelier(bot: "WallyTwitch"):
    """(bibliothèque, réglages, flux overlay), ou des None si rien n'est câblé.

    Tout passe par `dashboard_state`, posé sur le bot Twitch dans `main.py` —
    c'est là que vivent la bibliothèque de sons et le bus de l'overlay.
    """
    from bot.core.sons import ReglagesSons

    ds = getattr(bot, "dashboard_state", None)
    library = getattr(ds, "sons", None)
    feed = getattr(ds, "overlay_feed", None)
    if library is None or feed is None:
        return None, None, None
    return library, ReglagesSons(library.directory), feed


async def handle_son_command(bot: "WallyTwitch", commande: str) -> bool:
    """Joue le son nommé sur l'overlay. Rend False si ce n'est pas un son connu.

    Muet en cas de refus : ni message d'erreur, ni réponse dans le chat. Un son
    encore en cooldown qui répondrait « attends 42 s » ferait deux nuisances au
    lieu d'une — c'est précisément le spam qu'on veut éviter.
    """
    library, reglages, feed = _atelier(bot)
    if library is None:
        return False
    fichier = library.commandes().get(commande)
    if fichier is None:
        return False

    reglage = reglages.pour(commande)
    maintenant = time.monotonic()
    depuis = maintenant - _derniers.get(commande, float("-inf"))
    if depuis < reglage["cooldown"]:
        logger.info("Son !{c} ignoré — encore {n:.0f} s de cooldown",
                    c=commande, n=reglage["cooldown"] - depuis)
        return True

    _derniers[commande] = maintenant
    # Sans `scene` : un son demandé par le chat s'entend sur toutes les pages
    # d'overlay, quelle que soit la scène à l'antenne — comme `!image`.
    feed.publish({
        "type": "son",
        "genre": "commande",
        "nom": fichier,
        "volume": reglage["volume"],
    })
    logger.info("Son !{c} joué sur l'overlay ({f})", c=commande, f=fichier)
    return True
