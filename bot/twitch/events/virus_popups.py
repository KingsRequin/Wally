"""Spam de popups « virus » acheté aux points de chaîne.

De fausses fenêtres système et des memes en pièce jointe s'ouvrent de plus en
plus vite et s'empilent jusqu'à saturer l'écran, puis un écran bleu nettoie tout
— long et couvrant, c'est le but demandé. Cher (50 000 points par défaut), donc
le remboursement est la moitié sérieuse de ce module : chaque chemin où le spam
ne part pas rend les points ET le dit.

Ce module a d'abord porté l'avalanche de memes, montée en parallèle : l'owner a
tranché entre les deux le 2026-08-18, après les avoir vues tourner. Aucune
récompense n'ayant jamais pu naître (chaîne au plafond), la clé a pu être
renommée sans rien laisser d'orphelin.

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
CLE_RECOMPENSE = "overlay:virus_popup_reward_id"

TITRE = "Attaque de meme"
COUT = 50000
PROMPT = ("L'écran se fait submerger de fausses fenêtres de virus et de memes, "
          "de plus en plus vite, jusqu'à un blue screen.")

# Aucun champ de saisie : il n'y a rien à écrire, et `is_user_input_required`
# est optionnel côté Twitch — il était posé à `True` en dur pour tout le monde,
# héritage du duel qui attend un uid.
SAISIE_REQUISE = False

# Cinq minutes de recharge entre deux achats (owner, 2026-08-20). Le spectacle
# dure et couvre TOUT l'écran : deux achats coup sur coup enchaînaient deux fois
# la même chose, et le second passait pour un bug d'affichage.
#
# Tenu par TWITCH et non par nous : c'est lui qui refuse l'achat pendant le
# délai, donc il n'y a rien à faire payer puis à rembourser, et le bouton porte
# son compte à rebours sous les yeux du chat.
RECHARGE_S = 300


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
        logger.error("Spam de virus : remboursement en erreur : {e!r}", e=exc)
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    if rendu:
        texte = f"{mention}{motif} — tes points t'ont été rendus."
    else:
        texte = (f"{mention}{motif} — et je n'ai PAS pu te rendre tes points "
                 f"automatiquement, il faudra le faire manuellement "
                 f"(redemption {redemption_id}).")
    try:
        await bot.twitch_api.send_automatic(texte)
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("Spam de virus : refus non annoncé dans le chat : {e!r}", e=exc)


def _feed(bot, description: str) -> None:
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="virus_popup_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed : attaque de virus non consignée : {e!r}", e=exc)


async def lancer_spam_virus(bot: "WallyTwitch", *, acheteur: str, reward_id: str,
                           redemption_id: str) -> None:
    """Déclenche le spam, ou rend les points. N'échoue jamais vers l'appelant."""
    try:
        narrateur = _narrateur(bot)
        if narrateur is None or not narrateur.is_active():
            # Hors live, il n'y a pas d'écran à submerger : garder 50 000 points
            # pour un spectacle que personne ne verra serait du vol.
            logger.info("Spam de virus demandé hors live par {u} — remboursement", u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "l'écran n'est pas allumé, le spam n'a pas d'écran où s'afficher")
            return
        # Le retour est LU : sans ça, on annoncerait un spam qui n'a pas
        # eu lieu — l'écran a pu s'éteindre entre la vérification et l'envoi.
        if not narrateur.show_virus_popups():
            logger.warning("Spam de virus refusé par l'overlay — remboursement")
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "l'overlay n'a pas pu lancer le spam")
            return
        logger.info("Spam de virus lancé par {u}", u=acheteur)
        _feed(bot, f"{acheteur} a déclenché une attaque de virus (points de chaîne)")
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("Spam de virus en erreur : {e!r}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "le spam n'a pas pu être lancé (pépin technique)")
