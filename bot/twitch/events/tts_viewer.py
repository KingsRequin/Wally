"""Le TTS des viewers : on paie, Wally lit son message à voix haute.

Cousine de « im out » (`im_out.py`), à une différence près qui change tout : la
phrase n'est plus fixe, c'est le viewer qui l'écrit. Deux conséquences, et
elles sont la raison d'être de ce module plutôt qu'un paramètre de plus chez le
voisin :

  · **Le texte est de la donnée, jamais une instruction.** Il ne passe par
    aucun modèle — il part au TTS tel quel. Rien à reformuler, rien à
    interpréter : c'est un haut-parleur, pas une conversation. Les crochets
    sont retirés parce qu'ils pilotent le style de la voix (`[murmure]`,
    `[colère]` — cf. `voice/style.py`) : sans ça, le viewer choisirait le ton
    de Wally, et un message qui ne serait QUE des tags sortirait vide.
  · **Le pseudo est dit.** Un TTS anonyme ne s'attribue à personne : les gens
    du vocal entendraient une phrase surgie de nulle part dans la bouche de
    Wally. Le gabarit vit ici, en un seul endroit.

Le mot d'un pendu en cours n'a rien à craindre : `VoiceService.speak()` passe
tout ce qu'il dit par `redact()`, quelle que soit la provenance.

LE REMBOURSEMENT EST LA MOITIÉ SÉRIEUSE DU MODULE, comme chez toutes ses
voisines. Hors salon vocal Wally n'a pas de bouche ; en panne de TTS rien ne
sort ; un message vidé par le nettoyage n'a rien à lire. Chaque chemin où le
message n'est pas entendu rend les points ET le dit dans le chat.

Perception passive comme les autres événements de stream : on alimente le flux,
on ne réveille aucune cadence de parole.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# La clé où vit l'identifiant de NOTRE récompense. Distincte de toutes les
# autres : partagée, l'une deviendrait irremboursable et l'autre lancerait le
# mauvais effet — piège déjà nommé pour le duel, l'attaque de meme, l'humeur
# et « im out ».
CLE_RECOMPENSE = "voice:tts_viewer_reward_id"

TITRE = "tts wally"
COUT = 500
PROMPT = "Écris ce que Wally doit lire à voix haute dans le vocal du stream."

# Le viewer écrit : c'est toute la récompense.
SAISIE_REQUISE = True

# Une minute entre deux achats. Le quota Azure est un plafond MENSUEL de
# 500 k caractères (`voice/quota.py`) et la voix de Wally est un canal unique :
# sans recharge, une poignée d'achats enchaînés monopolise le salon et personne
# n'entend plus rien d'autre.
RECHARGE_S = 60

# Twitch plafonne déjà la saisie à 200 caractères, mais c'est SA limite, pas la
# nôtre : elle n'est pas dans le corps qu'on envoie, donc rien ne garantit
# qu'elle ne bougera pas. Un plafond ici tient quoi qu'il arrive.
LONGUEUR_MAX = 200

# Ce que Wally prononce vraiment. En un seul endroit, comme la phrase de
# « im out ».
GABARIT = "{acheteur} dit : {texte}"


def _nettoyer(texte: str) -> str:
    """Le message tel qu'il sera prononcé — vide s'il n'y a rien à dire.

    Les crochets partent parce qu'ils SONT le langage de commande de la voix
    (`resolve_style`) : les laisser passer donnerait au viewer la main sur le
    ton de Wally, et un message qui n'était que des tags ressortirait vide bien
    plus loin, dans `_speak_locked`, où plus personne ne sait qu'il y avait des
    points à rendre.
    """
    sans_tags = re.sub(r"\[[^\]]*\]", " ", texte or "")
    return " ".join(sans_tags.split())[:LONGUEUR_MAX]


def _feed(bot, description: str) -> None:
    feed = getattr(bot, "stream_feed", None)
    if feed is None:
        return
    try:
        feed.record(description, kind="tts_redemption")
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("StreamFeed : TTS viewer non consigné : {e!r}", e=exc)


async def _rendre(bot, acheteur: str, reward_id: str, redemption_id: str,
                  motif: str) -> None:
    """Rembourse et le dit. Dans cet ordre : si l'envoi Twitch lève, le viewer
    a déjà récupéré ses points.

    Le message dit AUSSI si le remboursement a réellement abouti — promettre
    des points qui ne reviendront pas est pire que de ne rien promettre.
    """
    rendu = False
    try:
        rendu = await bot.twitch_api.refund_redemption(reward_id, redemption_id)
    except Exception as exc:  # noqa: BLE001 — on annonce quand même
        logger.error("TTS viewer : remboursement en erreur : {e!r}", e=exc)
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
        logger.error("TTS viewer : refus non annoncé dans le chat : {e!r}", e=exc)


async def lire_message(bot: "WallyTwitch", *, acheteur: str, saisie: str,
                       reward_id: str, redemption_id: str) -> None:
    """Lit le message à voix haute, ou rend les points. Ne lève jamais."""
    try:
        texte = _nettoyer(saisie)
        if not texte:
            logger.info("TTS viewer : message vide de {u} — remboursement", u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "ton message n'avait rien à lire")
            return

        service = getattr(getattr(bot, "discord_bot", None), "voice_service", None)
        if service is None or not getattr(service, "is_connected", False):
            logger.info("TTS viewer acheté par {u} hors vocal — remboursement", u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "je ne suis dans aucun salon vocal, personne ne "
                          "m'aurait entendu")
            return

        # `malgre_ecoute` : pendant un live Wally est en écoute seule et
        # `speak()` refuse de parler pour ne pas couvrir le streamer. C'est
        # justement le moment où cette récompense sert, et un achat est une
        # demande on ne peut plus explicite — même arbitrage que « im out » et
        # `say_in_voice`.
        #
        # Le retour est LU : sans ça on encaisserait un silence. C'est le
        # `is_sent: false` du chat Twitch, transposé à la voix.
        prononce = GABARIT.format(acheteur=acheteur, texte=texte)
        if not await service.speak(prononce, malgre_ecoute=True):
            logger.warning("TTS viewer : la parole n'est pas sortie — remboursement")
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "ma voix n'est pas sortie")
            return
        logger.info("TTS viewer lu pour {u} : {t!r}", u=acheteur, t=texte)
        _feed(bot, f"{acheteur} a fait lire « {texte} » à Wally (points de chaîne)")
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("TTS viewer en erreur : {e!r}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "ton message n'a pas pu être lu (pépin technique)")
