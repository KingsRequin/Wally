"""Le TTS des viewers : on paie, Wally lit son message à voix haute.

Cousine de « im out » (`im_out.py`), à une différence près qui change tout : la
phrase n'est plus fixe, c'est le viewer qui l'écrit. Deux conséquences, et
elles sont la raison d'être de ce module plutôt qu'un paramètre de plus chez le
voisin :

  · **Le texte est de la donnée, jamais une instruction.** Il ne passe par
    aucun modèle — il part au TTS tel quel. Rien à reformuler, rien à
    interpréter : c'est un haut-parleur, pas une conversation.
  · **Le ton, lui, appartient au viewer.** Un tag de tête (`[murmure]`,
    `[colère]` — le vocabulaire de `voice/style.py`) est retenu et IMPOSÉ à
    la synthèse. C'est ce qu'on vend, et l'invite de la récompense le dit.
    Il voyage en donnée jusqu'à `speak(style=...)` plutôt que dans le texte :
    le message est enchâssé dans un gabarit, un tag laissé dedans ne serait
    plus en tête et `parse_style_tag` ne le verrait jamais. Les crochets
    RESTANTS partent quand même — didascalies et tags inconnus n'ont rien à
    faire dans la bouche de Wally — et un message qui n'était QUE des tags
    n'a plus rien à lire : il rend les points.
  · **Le pseudo est dit.** Un TTS anonyme ne s'attribue à personne : les gens
    du vocal entendraient une phrase surgie de nulle part dans la bouche de
    Wally. Le gabarit vit ici, en un seul endroit.

Le mot d'un pendu en cours n'a rien à craindre : `VoiceService.speak()` passe
tout ce qu'il dit par `redact()`, quelle que soit la provenance.

LE REMBOURSEMENT EST LA MOITIÉ SÉRIEUSE DU MODULE, comme chez toutes ses
voisines. Hors salon vocal Wally n'a pas de bouche ; en panne de TTS rien ne
sort ; un message vidé par le nettoyage n'a rien à lire ; une lecture déjà en
cours ou une recharge non écoulée refusent l'achat. Chaque chemin où le message
n'est pas entendu rend les points ET le dit dans le chat.

Perception passive comme les autres événements de stream : on alimente le flux,
on ne réveille aucune cadence de parole.
"""
from __future__ import annotations

import math
import re
import time
from typing import TYPE_CHECKING

from loguru import logger

from bot.discord.voice.style import parse_style_tag

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# La clé où vit l'identifiant de NOTRE récompense. Distincte de toutes les
# autres : partagée, l'une deviendrait irremboursable et l'autre lancerait le
# mauvais effet — piège déjà nommé pour le duel, l'attaque de meme, l'humeur
# et « im out ».
CLE_RECOMPENSE = "voice:tts_viewer_reward_id"

TITRE = "tts wally"
COUT = 500
PROMPT = (
    "Wally lit ton message à voix haute dans le vocal du stream. "
    "Commence par un ton entre crochets pour colorer sa voix : "
    "[murmure] [crie] [joyeux] [triste] [énervé] [excité] [peur] [surpris]"
)

# Le viewer écrit : c'est toute la récompense.
SAISIE_REQUISE = True

# Une minute entre deux achats D'UNE MÊME PERSONNE. Twitch ne sait poser qu'une
# recharge GLOBALE, qui bloquait tout le chat dès qu'un seul viewer achetait :
# la garde vit donc ici, et le module `main.py` n'arme plus aucun cooldown côté
# Twitch. Contrepartie assumée : Twitch laisse l'achat partir, donc le refus se
# paie d'un remboursement — c'est justement ce que ce module sait faire.
RECHARGE_PERSONNE_S = 60

# Le plafond est le NÔTRE : Twitch laisse passer plus que les 200 caractères
# qu'on lui prêtait — mesuré en prod le 2026-09-04, une tirade est arrivée
# entière et c'est ce plafond-ci qui l'a coupée en plein mot, en silence.
# 500 caractères, soit une trentaine de secondes de lecture : de quoi placer
# une tirade sans que la voix de Wally, qui est un canal unique, soit
# monopolisée. Au-delà, la coupe se fait au dernier mot ENTIER et le viewer en
# est prévenu dans le chat — une phrase tranchée au milieu d'une syllabe passe
# pour une panne.
LONGUEUR_MAX = 500

# Ce que Wally prononce vraiment. En un seul endroit, comme la phrase de
# « im out ».
GABARIT = "{acheteur} dit : {texte}"

# Dernier achat ENTENDU, par personne. En RAM : la valeur ne vaut qu'une
# minute, la persister coûterait une écriture en base pour un état qui a
# expiré avant le prochain démarrage.
_dernier_achat: dict[str, float] = {}

# Vrai pendant qu'un message acheté passe à la voix. `speak()` sérialise déjà
# ses appelants (`_speak_lock`), donc sans ce drapeau un second achat ne serait
# pas refusé : il ATTENDRAIT son tour, et le viewer entendrait sa phrase une
# minute plus tard sans comprendre pourquoi.
_lecture_en_cours = False


def _cle(acheteur: str) -> str:
    """Le login Twitch, replié : « Alice » et « alice » sont la même personne."""
    return (acheteur or "?").casefold()


def _attente_restante(acheteur: str) -> int:
    """Secondes restantes avant que `acheteur` puisse racheter — 0 s'il peut."""
    dernier = _dernier_achat.get(_cle(acheteur))
    if dernier is None:
        return 0
    return max(0, math.ceil(RECHARGE_PERSONNE_S - (time.monotonic() - dernier)))


def _armer_recharge(acheteur: str) -> None:
    """Démarre la recharge de `acheteur`, et purge celles qui ont expiré.

    Appelé APRÈS une lecture réellement sortie, jamais avant : un achat
    remboursé (hors vocal, panne Azure) ne doit pas bloquer une minute
    quelqu'un qui n'a rien entendu.

    Sans la purge, le dictionnaire garderait une entrée par viewer à vie, pour
    une valeur qui ne dit plus rien passé la minute.
    """
    maintenant = time.monotonic()
    for cle, quand in list(_dernier_achat.items()):
        if maintenant - quand >= RECHARGE_PERSONNE_S:
            del _dernier_achat[cle]
    _dernier_achat[_cle(acheteur)] = maintenant


def _tronquer(texte: str) -> tuple[str, bool]:
    """(message tenu sous le plafond, a-t-il fallu couper ?).

    La coupe se fait au dernier mot ENTIER : Azure prononce ce qu'on lui donne,
    et un mot tranché au milieu s'entend comme un bug de synthèse. Un mot seul
    plus long que le plafond n'a pas de frontière où se replier — on le coupe
    net plutôt que de rendre du vide.
    """
    if len(texte) <= LONGUEUR_MAX:
        return texte, False
    coupe = texte[:LONGUEUR_MAX].rsplit(" ", 1)[0] or texte[:LONGUEUR_MAX]
    return coupe, True


def _decouper(texte: str) -> tuple[str | None, str, bool]:
    """(style Azure demandé, message à prononcer, message tronqué ?).

    Message vide s'il n'y a rien à dire.

    Le tag de TÊTE est lu par `parse_style_tag`, exactement comme quand Wally
    s'écrit un ton à lui-même : une seule table de correspondance pour les
    deux, sinon `[colere]` marcherait d'un côté et pas de l'autre. Un tag
    inconnu n'est pas une panne — il est retiré sans style, le message part
    quand même.

    Les crochets qui restent (didascalies, second tag) sont supprimés : ils
    n'ont rien à faire dans la bouche de Wally. Ce qui n'en laisse rien
    ressortirait vide bien plus loin, dans `_speak_locked`, où plus personne ne
    sait qu'il y avait des points à rendre — d'où le message vide rendu ICI.
    """
    style, reste = parse_style_tag(texte or "")
    sans_tags = re.sub(r"\[[^\]]*\]", " ", reste)
    message, tronque = _tronquer(" ".join(sans_tags.split()))
    return style, message, tronque


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
        # ORANGE : une récompense payée qui n'a pas pu être honorée. Le viewer
        # doit repérer la ligne qui le concerne dans un chat qui défile — c'est
        # la seule annonce où il a perdu quelque chose.
        await bot.twitch_api.send_automatic(
            texte, color=bot.twitch_api.COULEUR_ECHEC)
    except Exception as exc:  # noqa: BLE001 — le remboursement est déjà fait
        logger.error("TTS viewer : refus non annoncé dans le chat : {e!r}", e=exc)


async def _prevenir_coupe(bot, acheteur: str) -> None:
    """Dit dans le chat que le message a été raccourci. Ne rembourse RIEN : le
    viewer a bien été entendu, il a seulement été entendu en partie.

    Sans ce mot, la coupe est indiscernable d'une panne — c'est exactement ce
    qui s'est vu en live le 2026-09-04, où personne au vocal ne comprenait
    pourquoi la tirade s'arrêtait au milieu.
    """
    mention = f"@{acheteur} " if acheteur and acheteur != "?" else ""
    try:
        # ORANGE comme un remboursement : le viewer a payé et n'a pas eu tout
        # ce qu'il attendait. C'est la ligne qu'il doit voir passer.
        await bot.twitch_api.send_automatic(
            f"{mention}ton message dépassait {LONGUEUR_MAX} caractères, "
            f"j'en ai lu le début seulement.",
            color=bot.twitch_api.COULEUR_ECHEC)
    except Exception as exc:  # noqa: BLE001 — le message est passé, lui
        logger.error("TTS viewer : coupe non annoncée dans le chat : {e!r}", e=exc)


async def lire_message(bot: "WallyTwitch", *, acheteur: str, saisie: str,
                       reward_id: str, redemption_id: str) -> None:
    """Lit le message à voix haute, ou rend les points. Ne lève jamais."""
    global _lecture_en_cours
    try:
        # Les deux gardes de cadence AVANT tout le reste : elles ne coûtent
        # rien et ce sont les seuls refus où le viewer n'a rien fait de mal.
        if _lecture_en_cours:
            logger.info("TTS viewer : lecture déjà en cours, achat de {u} refusé",
                        u=acheteur)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "je suis déjà en train de lire le message de quelqu'un")
            return
        restant = _attente_restante(acheteur)
        if restant:
            logger.info("TTS viewer : {u} en recharge ({s} s restantes)",
                        u=acheteur, s=restant)
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          f"attends encore {restant} s avant de m'en faire lire "
                          f"un autre")
            return

        ton, texte, tronque = _decouper(saisie)
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
        # Le ton part en DONNÉE, pas dans le texte : enchâssé dans le gabarit
        # il ne serait plus en tête, et `parse_style_tag` ne le verrait jamais.
        # `speak()` le ramène aux capacités de la voix montée.
        prononce = GABARIT.format(acheteur=acheteur, texte=texte)
        # Le drapeau se pose SANS `await` entre le test plus haut et ici :
        # c'est ce qui en fait un verrou dans une boucle d'événements.
        _lecture_en_cours = True
        try:
            sortie = await service.speak(prononce, malgre_ecoute=True, style=ton)
        finally:
            _lecture_en_cours = False
        if not sortie:
            logger.warning("TTS viewer : la parole n'est pas sortie — remboursement")
            await _rendre(bot, acheteur, reward_id, redemption_id,
                          "ma voix n'est pas sortie")
            return
        _armer_recharge(acheteur)
        logger.info("TTS viewer lu pour {u} ({s}{c}) : {t!r}",
                    u=acheteur, s=ton or "ton par défaut",
                    c=", TRONQUÉ" if tronque else "", t=texte)
        if tronque:
            await _prevenir_coupe(bot, acheteur)
        _feed(bot, f"{acheteur} a fait lire « {texte} » à Wally (points de chaîne)")
    except Exception as exc:  # noqa: BLE001 — un handler ne tue jamais le bot
        logger.error("TTS viewer en erreur : {e!r}", e=exc)
        await _rendre(bot, acheteur, reward_id, redemption_id,
                      "ton message n'a pas pu être lu (pépin technique)")
