"""Avalanche de memes achetée aux points de chaîne.

Une pluie submerge l'écran jusqu'à ce que TOUT le dossier de memes soit passé
(~40 s pour 134 memes) — long et couvrant, c'est le but demandé. Cher
(50 000 points par défaut), donc le remboursement est la moitié sérieuse de ce
module : chaque chemin où l'avalanche ne tombe pas rend les points ET le dit.

Perception passive comme les autres événements de stream : on alimente le flux,
on ne réveille aucune cadence de parole.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# La clé où vit l'identifiant de NOTRE récompense. Distincte de celle du duel :
# partagée, l'une des deux deviendrait irremboursable et l'autre lancerait le
# mauvais effet.
CLE_RECOMPENSE = "overlay:avalanche_reward_id"

TITRE = "Avalanche de memes"
COUT = 50000
PROMPT = ("Une pluie submerge l'écran jusqu'à ce que TOUS les memes de la "
          "communauté soient passés. Rien à écrire, ça part tout seul.")


def _narrateur(bot):
    return getattr(getattr(bot, "discord_bot", None), "overlay_narrator", None)


async def _rendre(bot, acheteur: str, reward_id: str, redemption_id: str,
                  motif: str) -> None:
    """Rembourse et le dit. Dans cet ordre : si l'envoi Twitch lève, le viewer
    a déjà récupéré ses points.

    Le message dit AUSSI si le remboursement a réellement abouti. Promettre des
    points qui ne reviendront pas est pire que de ne rien promettre — c'est la
    règle déjà retenue pour le duel.
    """
    rendu = False
    try:
        rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
    except Exception as exc:  # noqa: BLE001 — on annonce quand même
        logger.error("Avalanche : remboursement en erreur : {e}", e=exc)
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    if rendu:
        texte = f"{mention}{motif} — tes points t'ont été rendus."
    else:
        texte = (f"{mention}{motif} — et je n'ai PAS pu te rendre tes points "
                 f"automatiquement, il faudra le faire manuellement "
                 f"(redemption {redemption_id}).")
    try:
        await bot.twitch_api.send_message(text=texte)
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("Avalanche : refus non annoncé dans le chat : {e}", e=exc)


def _feed(bot, description: str) -> None:
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="avalanche_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed : avalanche non consignée : {e}", e=exc)


async def lancer_avalanche(bot: "WallyTwitch", *, acheteur: str, reward_id: str,
                           redemption_id: str) -> None:
    """Déclenche l'avalanche, ou rend les points. N'échoue jamais vers l'appelant."""
    try:
        narrateur = _narrateur(bot)
        if narrateur is None or not narrateur.is_active():
            # Hors live, il n'y a pas d'écran à submerger : garder 50 000 points
            # pour un spectacle que personne ne verra serait du vol.
            logger.info("Avalanche demandée hors live par {u} — remboursement", u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "l'écran n'est pas allumé, l'avalanche ne peut pas tomber")
            return
        # Le retour est LU : sans ça, on annoncerait une avalanche qui n'a pas
        # eu lieu — l'écran a pu s'éteindre entre la vérification et l'envoi.
        if not narrateur.show_meme_storm():
            logger.warning("Avalanche refusée par l'overlay — remboursement")
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "l'overlay n'a pas pu lancer l'avalanche")
            return
        logger.info("Avalanche de memes lancée par {u}", u=acheteur)
        _feed(bot, f"{acheteur} a déclenché une avalanche de memes (points de chaîne)")
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Avalanche en erreur : {e}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "l'avalanche n'a pas pu être lancée (pépin technique)")
