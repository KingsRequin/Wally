"""« im out » aux points de chaîne : Wally le dit à voix haute, et c'est tout.

Une phrase FIXE, sans appel au modèle. C'est un bouton, pas une conversation :
le viewer paie, la voix de Wally sort dans le salon vocal, fin. Faire reformuler
le modèle aurait ajouté une latence et un coût pour dénaturer la seule chose
qu'on achète — le gag tient à ce que ce soit toujours exactement la même
réplique.

Même architecture que l'attaque de meme, et pour les mêmes raisons : Twitch ne
laisse rembourser qu'à l'application qui a CRÉÉ la récompense, donc Wally la
crée au démarrage et son identifiant est découvert à l'exécution — jamais écrit
en configuration.

LE REMBOURSEMENT EST LA MOITIÉ SÉRIEUSE DU MODULE. Hors salon vocal, Wally n'a
pas de bouche ; en panne de TTS, rien ne sort. Chaque chemin où la phrase n'est
pas entendue rend les points ET le dit dans le chat. C'est ce qui a fait poser
un vrai retour sur `VoiceService.speak()`, qui jusqu'ici se taisait en silence.

Perception passive comme les autres événements de stream : on alimente le flux,
on ne réveille aucune cadence de parole.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# La clé où vit l'identifiant de NOTRE récompense. Distincte de toutes les
# autres : partagée, l'une deviendrait irremboursable et l'autre lancerait le
# mauvais effet — piège déjà nommé pour le duel, l'attaque de meme et l'humeur.
CLE_RECOMPENSE = "voice:im_out_reward_id"

TITRE = "Faire dire im out a wally"
COUT = 500
PROMPT = "Wally lâche « I'm out » à voix haute dans le vocal du stream."

# Rien à écrire : la phrase ne se choisit pas, c'est tout l'intérêt.
SAISIE_REQUISE = False

# La phrase, en toutes lettres et en un seul endroit. Elle part telle quelle au
# TTS : l'apostrophe droite et non typographique, c'est ce qu'Azure prononce le
# mieux, et le SSML n'a rien à échapper ici.
PHRASE = "I'm out"


def _feed(bot, description: str) -> None:
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="im_out_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed : « im out » non consigné : {e!r}", e=exc)


async def _rendre(bot, acheteur: str, reward_id: str, redemption_id: str,
                  motif: str) -> None:
    """Rembourse et le dit. Dans cet ordre : si l'envoi Twitch lève, le viewer
    a déjà récupéré ses points.

    Le message dit AUSSI si le remboursement a réellement abouti — promettre des
    points qui ne reviendront pas est pire que de ne rien promettre. Règle
    retenue pour le duel, puis pour l'attaque de meme.
    """
    rendu = False
    try:
        rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
    except Exception as exc:  # noqa: BLE001 — on annonce quand même
        logger.error("« im out » : remboursement en erreur : {e!r}", e=exc)
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    if rendu:
        texte = f"{mention}{motif}, tes points t'ont été rendus."
    else:
        texte = (f"{mention}{motif}, et je n'ai PAS pu te rendre tes points "
                 f"automatiquement, il faudra le faire manuellement "
                 f"(redemption {redemption_id}).")
    try:
        await bot.twitch_api.send_automatic(texte)
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("« im out » : refus non annoncé dans le chat : {e!r}", e=exc)


async def dire_im_out(bot: "WallyTwitch", *, acheteur: str, reward_id: str,
                      redemption_id: str) -> None:
    """Dit la phrase à voix haute, ou rend les points. Ne lève jamais."""
    try:
        service = getattr(getattr(bot, "discord_bot", None), "voice_service", None)
        if service is None or not getattr(service, "is_connected", False):
            logger.info("« im out » acheté par {u} hors vocal — remboursement", u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "je ne suis dans aucun salon vocal, personne ne "
                          "m'aurait entendu")
            return
        # `malgre_ecoute` : pendant un live Wally est en écoute seule et
        # `speak()` refuse de parler pour ne pas couvrir le streamer. C'est
        # justement le moment où cette récompense sert, et un achat est une
        # demande on ne peut plus explicite — même arbitrage que `say_in_voice`.
        #
        # Le retour est LU : sans ça on encaisserait un silence. C'est le
        # `is_sent: false` du chat Twitch, transposé à la voix.
        if not await service.speak(PHRASE, malgre_ecoute=True):
            logger.warning("« im out » : la parole n'est pas sortie — remboursement")
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "ma voix n'est pas sortie")
            return
        logger.info("« im out » dit à voix haute pour {u}", u=acheteur)
        _feed(bot, f"{acheteur} a fait dire « {PHRASE} » à Wally (points de chaîne)")
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("« im out » en erreur : {e!r}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "la phrase n'a pas pu sortir (pépin technique)")
