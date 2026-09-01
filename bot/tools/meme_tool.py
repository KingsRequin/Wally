"""Envoi d'un meme dans un salon Discord.

Wally n'avait qu'un outil meme : celui de l'overlay OBS. Demandé depuis Discord,
le meme partait donc devant les viewers Twitch, et Wally répondait « c'est à
l'écran » — un écran que son interlocuteur ne voit pas. Sur Discord, il était
donc IMPOSSIBLE d'obtenir un meme, quoi qu'on demande.

Le modèle ne voit toujours qu'un seul outil, `show_overlay` avec `widget=meme` :
c'est l'ADAPTATEUR qui décide de la destination, comme pour le rébus. Deux
outils pour une seule idée feraient hésiter le modèle, et la question « où ? »
n'est pas la sienne — elle est déjà répondue par l'endroit où on lui parle.

Rien ne change côté Twitch : là-bas, l'écran est la bonne surface.
"""
from __future__ import annotations

import asyncio
import json

from loguru import logger


def _bibliotheque(bot):
    """La réserve de memes, ou None. Même source que l'overlay.

    Passer par l'état du dashboard plutôt que par le narrateur : le narrateur la
    garde en privé, et un meme envoyé dans un salon n'a aucune raison d'exiger
    qu'un overlay soit branché — encore moins qu'un live tourne.
    """
    etat = getattr(bot, "dashboard_state", None)
    return getattr(etat, "memes", None) if etat is not None else None


async def run_meme_tool_discord(bot, channel, args: dict) -> str:
    """Envoie un meme dans `channel` et rend le compte rendu destiné à Wally.

    Le compte rendu porte la DESCRIPTION du meme : Wally ne voit pas l'image, et
    sans elle il commenterait à l'aveugle. Elle ne part pas en légende pour
    autant — elle est écrite pour lui, pas pour le salon, et doublerait sa
    propre phrase.
    """
    library = _bibliotheque(bot)
    if library is None:
        return json.dumps({"status": "unavailable",
                           "message": "La réserve de memes n'est pas branchée."})

    choisi = library.pick(str(args.get("about") or ""))
    if choisi is None:
        # `pick` rend None sur une réserve vide comme sur un sujet absent. Les
        # deux se disent de la même façon à Wally : il n'a pas ce meme. En
        # envoyer un au hasard referait exactement ce qu'on a retiré du tirage.
        return json.dumps({"status": "empty", "message": (
            "Aucun meme là-dessus dans la réserve. Dis-le simplement, "
            "n'en invente pas un."
        )})

    chemin = library.resolve(choisi["name"])
    if chemin is None:
        logger.warning("Meme {n} choisi mais introuvable à l'envoi", n=choisi["name"])
        return json.dumps({"status": "error",
                           "message": "Le fichier du meme est introuvable."})

    try:
        import discord

        # `discord.File` OUVRE le fichier : construit dans la boucle, il ferait
        # une lecture disque synchrone à chaque meme.
        fichier = await asyncio.to_thread(discord.File, chemin)
        await channel.send(file=fichier)
    except Exception as exc:  # noqa: BLE001 — un envoi raté ne casse pas la réponse
        logger.warning("Meme {n} non envoyé sur Discord : {e!r}",
                       n=choisi["name"], e=exc)
        return json.dumps({"status": "error", "message": (
            "L'envoi a échoué, le meme n'est PAS arrivé dans le salon. "
            "Ne prétends pas l'avoir montré."
        )})

    logger.info("Meme {n} envoyé dans le salon Discord {c}",
                n=choisi["name"], c=getattr(channel, "id", "?"))
    return json.dumps({"status": "ok", "message": (
        f"Le meme « {choisi['description']} » vient d'être envoyé dans le salon. "
        "Commente-le en une phrase — ne recopie pas cette description, "
        "elle est écrite pour toi, le salon voit déjà l'image."
    )})
