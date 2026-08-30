"""Les messages vocaux Discord — ce que Wally a demandé lui-même.

Désir écrit par lui le 2026-08-20, encore ouvert en base (`atomic_facts`,
`user_id='wally:self'`, `category='DESIRE'`) :

    « Capacité qui manquerait vraiment : transcrire les messages vocaux
    Discord. Les gens m'en envoient et je ne peux rien en faire. »

C'était pire que ce qu'il décrivait. `handlers.py` ne posait un marqueur que
pour les pièces jointes `image/` ; un message vocal est un `audio/ogg` dont le
`content` est **vide**. Il n'arrivait donc pas comme « un truc que je ne sais
pas lire », mais comme un message VIDE : Wally ne savait même pas que quelqu'un
lui avait parlé.

## Pourquoi c'est SYNCHRONE, contrairement aux images

Une image accompagne un message ; sa description peut arriver après coup, en
arrière-plan, et la réponse tient debout sans elle. Un vocal, lui, EST le
message : répondre à « [a envoyé un message vocal] » sans savoir ce qui est dit,
c'est ne pas répondre. La transcription passe donc avant la réponse.

## Le plafond de durée vient d'une MESURE

`scripts/bench_stt.py` sur six énoncés réels du live, dans le conteneur, modèle
`small` en int8 sur CPU : **1,74× le temps réel**, plus 6,3 s de chargement au
tout premier appel. Un vocal de 30 s coûte donc ~17 s, un de 60 s ~34 s.

Au-delà du plafond on ne transcrit pas, et on le DIT — « un message vocal de
4 minutes » est une information que Wally peut donner, là où quatre minutes
d'attente ne sont pas une réponse.

## L'étage STT : le local, et seulement lui

Un message vocal n'a aucune contrainte de latence, contrairement au vocal en
direct. Brûler du quota GPU distant ou de la soupape xAI pour un fichier qui
peut attendre trente secondes serait payer une urgence qui n'existe pas.
L'instance est chargée à la première transcription et pas au boot : sans message
vocal, elle ne coûte pas un octet.
"""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

# Au-delà, on ne transcrit pas. 60 s d'audio valent ~34 s de calcul sur ce CPU
# (1,74× le temps réel, mesuré) : c'est déjà le haut de ce qu'une conversation
# supporte. Un vocal plus long est annoncé pour ce qu'il est.
DUREE_MAX_S = 60.0

# Plafond de TÉLÉCHARGEMENT, pour les fichiers dont Discord ne donne pas la
# durée. Estimer une durée à partir de la taille serait faux : un `.mp3` à
# 128 kbit/s pèse quatre fois un Opus à 32, et un vocal de 20 s se ferait
# rejeter comme s'il en durait 80. On ne devine donc rien — on borne le poids,
# et la durée EXACTE se lit après décodage, avant de payer la transcription.
TAILLE_MAX_OCTETS = 8 * 1024 * 1024

# Le PCM attendu par `FasterWhisperSTT` : 16 kHz, mono, 16 bits signés.
_TAUX = 16000

_stt: Any = None
_verrou = asyncio.Lock()


def piece_jointe_vocale(message: Any) -> Any:
    """La première pièce jointe audio d'un message, ou `None`.

    On ne se limite PAS au drapeau `MessageFlags.voice` : un `.ogg` ou un `.mp3`
    déposé dans le salon pose exactement le même problème — du son que Wally ne
    sait pas lire — et le traiter demande le même geste.
    """
    for piece in getattr(message, "attachments", None) or []:
        type_mime = getattr(piece, "content_type", None) or ""
        if type_mime.startswith("audio/"):
            return piece
    return None


def duree_annoncee(piece: Any) -> float | None:
    """La durée que DISCORD annonce, ou `None` s'il n'en annonce pas.

    Présente pour les messages vocaux natifs, absente pour un fichier audio
    simplement glissé dans le salon. `None` veut dire « on ne sait pas », jamais
    « c'est court » : le seul verdict sûr se lit après décodage.
    """
    duree = getattr(piece, "duration", None)
    if not duree:
        return None
    try:
        return float(duree)
    except (TypeError, ValueError):
        logger.debug("Message vocal : durée annoncée illisible, on décodera pour savoir")
        return None


async def _en_pcm(donnees: bytes) -> bytes:
    """Décode n'importe quel conteneur audio en PCM 16 kHz mono, via ffmpeg.

    `FasterWhisperSTT` attend du PCM brut ; Discord envoie de l'Opus dans un
    conteneur OGG. ffmpeg est dans l'image (7.1.5) et lit sur `stdin`, donc rien
    ne touche le disque — un vocal ne laisse pas de fichier derrière lui.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", "pipe:0",
        "-f", "s16le", "-ac", "1", "-ar", str(_TAUX), "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    sortie, erreur = await proc.communicate(donnees)
    if proc.returncode != 0:
        logger.warning(
            "Message vocal : ffmpeg a refusé ({code}) — {err}",
            code=proc.returncode, err=(erreur or b"").decode("utf-8", "replace")[:200],
        )
        return b""
    return sortie


async def _moteur(config: Any) -> Any:
    """L'instance STT locale, chargée à la PREMIÈRE transcription.

    Sérialisé : deux messages vocaux qui arrivent ensemble chargeraient deux
    fois le modèle et doubleraient la mémoire.
    """
    global _stt
    async with _verrou:
        if _stt is None:
            from bot.discord.voice.providers import FasterWhisperSTT

            voix = getattr(config, "voice", None)
            _stt = FasterWhisperSTT(
                model_size=getattr(voix, "whisper_model", None) or "small",
                language=getattr(voix, "language", None) or "fr-FR",
                compute_type=getattr(voix, "whisper_compute_type", None) or "int8",
            )
        return _stt


async def transcrire(piece: Any, config: Any) -> str:
    """Le texte d'un message vocal. `""` si on n'a rien pu en tirer.

    Ne lève jamais : un message vocal illisible doit laisser passer le message,
    pas faire tomber le handler.
    """
    try:
        donnees = await piece.read()
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Message vocal : téléchargement impossible ({e!r})", e=exc)
        return ""

    pcm = await _en_pcm(donnees)
    if not pcm:
        return ""

    duree = len(pcm) / 2 / _TAUX
    if duree > DUREE_MAX_S:
        # Le décodage est bon marché, la transcription non : c'est ici qu'on
        # abandonne, avec la durée EXACTE plutôt qu'une devinette sur la taille.
        logger.info("Message vocal : {d:.0f} s après décodage, au-dessus du plafond", d=duree)
        return ""
    logger.info("Message vocal : {d:.1f} s à transcrire", d=duree)
    try:
        moteur = await _moteur(config)
        texte = await moteur.transcribe(pcm)
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Message vocal : transcription impossible ({e!r})", e=exc)
        return ""
    if not texte:
        logger.info("Message vocal : rien d'intelligible dans {d:.1f} s", d=duree)
    return texte.strip()


async def marqueur(message: Any, config: Any) -> tuple[str, str]:
    """`(ce qui entre dans le contexte, le texte nu)`. `("", "")` si aucun vocal.

    Trois sorties possibles pour la première, et les trois disent la vérité : la
    transcription, « trop long » avec sa durée, ou « je n'ai rien compris ».
    Aucune ne laisse croire à un message vide.

    Le texte NU est rendu à part parce qu'il sert ailleurs : c'est lui qu'on
    ajoute au contenu qui décide du déclenchement. Sans ça, quelqu'un qui dit
    « Wally, tu peux… » à l'oral ne déclencherait rien — `message.content` d'un
    vocal est vide, et le marqueur ne contient pas ce qui a été dit.
    """
    piece = piece_jointe_vocale(message)
    if piece is None:
        return "", ""

    # Deux gardes AVANT tout téléchargement, chacune sur ce qu'on sait vraiment.
    duree = duree_annoncee(piece)
    if duree is not None and duree > DUREE_MAX_S:
        logger.info("Message vocal ignoré : {d:.0f} s annoncées", d=duree)
        return (
            f"[a envoyé un message vocal de {round(duree)} s, trop long pour que tu l'écoutes]",
            "",
        )
    taille = int(getattr(piece, "size", 0) or 0)
    if taille > TAILLE_MAX_OCTETS:
        logger.info("Message vocal ignoré : {m:.1f} Mo", m=taille / 1024 / 1024)
        return "[a envoyé un fichier audio trop lourd pour que tu l'écoutes]", ""

    texte = await transcrire(piece, config)
    if not texte:
        return "[a envoyé un message vocal, mais tu n'as rien pu en tirer]", ""
    return f"[message vocal] {texte}", texte
