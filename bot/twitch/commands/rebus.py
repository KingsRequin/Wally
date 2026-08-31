"""Le rébus du chat : `!rebus` tire une énigme, le chat devine en écrivant.

DANS LE CHAT, pas sur l'overlay (arbitrage owner du 2026-08-31) : ce ne sont que
des emoji, une ligne suffit, et ça évite d'ouvrir un widget pour trois pictos.
C'est aussi ce qui rend le jeu jouable en replay et depuis le téléphone.

Trois choses appartiennent au SERVEUR, comme pour les sons et les popups :
la cadence des indices, le cooldown entre deux parties, et le tirage. Rien de
tout ça ne se délègue au chat.

⚠️ `secret_guard` tient la réponse pendant la partie : Wally continue de parler
aux gens, mais le mot est masqué dans TOUT ce qu'il publie. Sans ce filet, on lui
demande « c'est quoi la réponse » et il la donne — il est serviable, c'est son
défaut ici. Le filet se LÈVE avant la révélation, sinon Wally masquerait sa
propre annonce de fin : c'est le piège exact rencontré sur « deux vérités un
mensonge », où `secret_guard` aurait caviardé le sondage qui affichait le
mensonge.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from bot.core.rebus import Rebus, Sac, charger, indices, trouve
from bot.core.secret_guard import guard_secret, release_secret

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Un indice toutes les 40 s, et la partie meurt 40 s après le dernier. Un rébus
# à 4 jetons vit donc ~3 min. Mesuré sur rien : c'est un point de départ, à
# corriger en regardant ce que le chat trouve et à quel indice il décroche.
DELAI_INDICE_S = 40.0
# Deux minutes de repos entre deux parties : `!rebus` est ouvert à TOUT le chat,
# et sans cooldown trois personnes l'enchaînent et le jeu devient du bruit.
COOLDOWN_S = 120.0


@dataclass
class Partie:
    """Ce qui tourne. Une seule à la fois, sur la chaîne maison."""

    rebus: Rebus
    canal: str
    a_donner: list[str]
    tache: asyncio.Task | None = field(default=None, repr=False)


# En RAM, comme le cooldown des sons : une partie ne survit pas à un rebuild, et
# c'est assumé — au pire une énigme est perdue et le chat en relance une. La
# persistance coûterait une table pour un objet qui vit trois minutes.
_partie: Partie | None = None
_sac: Sac | None = None
_fin_derniere: float = float("-inf")


def _tirage() -> Sac | None:
    """Le sac, chargé au premier usage. None si le catalogue est vide."""
    global _sac
    if _sac is None:
        rebus = charger()
        if not rebus:
            return None
        _sac = Sac(rebus)
    return _sac


async def _publier(bot: "WallyTwitch", texte: str) -> None:
    """Une ligne dans le chat. Muet si l'API manque — jamais bloquant."""
    api = getattr(bot, "twitch_api", None)
    if api is None:
        logger.warning("Rébus : pas d'API Twitch, rien publié")
        return
    try:
        await api.send_automatic(texte)
    except Exception as exc:  # noqa: BLE001 — un jeu n'interrompt pas le bot
        logger.error("Rébus : ligne non publiée : {e!r}", e=exc)


def _oublier(*, gagne: bool) -> Rebus | None:
    """Clôt la partie et LÈVE le filet. Point de sortie unique.

    Unique comme `_release_hangman_secret` l'est pour le pendu, et pour la même
    raison : un sixième chemin qui remettrait `_partie = None` tout seul
    laisserait le mot masqué pour toujours, et la panne serait invisible — Wally
    se mettrait à trouer ses phrases des semaines plus tard sans que personne ne
    fasse le lien.
    """
    global _partie, _fin_derniere
    if _partie is None:
        return None
    rebus = _partie.rebus
    # `is not asyncio.current_task()` : quand le TEMPS expire, c'est le minuteur
    # lui-même qui clôt la partie. S'annuler soi-même lève un CancelledError au
    # prochain `await`, donc AVANT la révélation : le mot n'était jamais donné,
    # la partie mourait en silence et rien dans les logs ne l'expliquait.
    if _partie.tache is not None and _partie.tache is not asyncio.current_task():
        _partie.tache.cancel()
    release_secret(rebus.mot)
    _partie = None
    _fin_derniere = time.monotonic()
    logger.info("Rébus terminé ({r}) — mot : {m}", r="gagné" if gagne else "personne",
                m=rebus.mot)
    return rebus


async def _annoncer_fin(bot: "WallyTwitch", canal: str, fait: str) -> None:
    """La fin passe par l'annonce colorée, en voix de Wally.

    Le FAIT est calculé ici et publié tel quel si le LLM échoue : `JeuAnnouncer`
    ne fait qu'habiller, il ne décide de rien. Même règle que le pendu et le
    sondage.
    """
    from bot.twitch.jeu_announce import JeuAnnouncer

    await JeuAnnouncer(bot, canal).annoncer("rébus", fait)


async def _minuteur(bot: "WallyTwitch") -> None:
    """Distille les indices, puis rend le mot si personne ne l'a eu."""
    try:
        while True:
            await asyncio.sleep(DELAI_INDICE_S)
            if _partie is None:
                return
            if not _partie.a_donner:
                break
            indice = _partie.a_donner.pop(0)
            await _publier(bot, f"🧩 Indice : {indice}. → {_partie.rebus.enigme}")
        canal = _partie.canal
        # LEVER le filet AVANT d'annoncer : `redact()` masque le mot dans tout
        # ce qui sort, y compris dans la phrase qui le révèle. Annoncer d'abord
        # publierait « le mot était ███ ».
        rebus = _oublier(gagne=False)
        if rebus is not None:
            await _annoncer_fin(bot, canal, f"personne n'a trouvé le rébus {rebus.enigme} : "
                                            f"c'était {rebus.mot.upper()} ({rebus.solution}).")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — le minuteur ne tue pas le bot
        logger.error("Rébus : minuteur interrompu : {e!r}", e=exc)


async def handle_rebus_command(bot: "WallyTwitch", canal: str) -> None:
    """`!rebus` — relance l'énigme en cours, ou en tire une neuve."""
    global _partie
    if _partie is not None:
        # Pas un refus : le chat défile, et quelqu'un qui arrive en cours de
        # partie a le droit de revoir l'énigme. Répondre « une partie est déjà
        # en cours » sans la redonner serait deux fois inutile.
        await _publier(bot, f"🧩 Toujours en jeu : {_partie.rebus.enigme}")
        return

    repos = time.monotonic() - _fin_derniere
    if repos < COOLDOWN_S:
        # Muet, comme les sons en cooldown : un « attends 42 s » est la seconde
        # nuisance qu'on cherche justement à éviter.
        logger.info("Rébus ignoré — encore {n:.0f} s de repos", n=COOLDOWN_S - repos)
        return

    sac = _tirage()
    rebus = sac.tirer() if sac is not None else None
    if rebus is None:
        logger.warning("Rébus : aucune énigme disponible, commande sans effet")
        return

    guard_secret(rebus.mot)
    _partie = Partie(rebus=rebus, canal=canal, a_donner=indices(rebus))
    logger.info("Rébus lancé : {e} → {m}", e=rebus.enigme, m=rebus.mot)
    await _publier(bot, f"🧩 Rébus ! Prononcez les dessins et devinez le mot : {rebus.enigme}")
    _partie.tache = asyncio.create_task(_minuteur(bot))


async def verifier_reponse(bot: "WallyTwitch", auteur: str, contenu: str) -> bool:
    """Ce message gagne-t-il la partie ? Appelé sur CHAQUE ligne du chat maison.

    Rend True quand la partie est gagnée — pas pour bloquer le message (le chat
    reste du chat), mais pour que l'appelant sache qu'il s'est passé quelque
    chose. Sort en une comparaison quand aucune partie ne tourne, ce qui est le
    cas 99 % du temps.
    """
    if _partie is None or not trouve(_partie.rebus, contenu):
        return False
    canal = _partie.canal
    rebus = _oublier(gagne=True)
    if rebus is None:  # deux bonnes réponses dans la même milliseconde
        return False
    await _annoncer_fin(bot, canal, f"{auteur} a trouvé le rébus {rebus.enigme} : "
                                    f"{rebus.mot.upper()} ({rebus.solution}).")
    return True
