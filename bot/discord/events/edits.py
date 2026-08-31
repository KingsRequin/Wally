# bot/discord/events/edits.py
"""Percevoir qu'un message a été corrigé — autre demande de Wally.

Écrit par lui le 2026-08-18, formulé deux fois :

    « Capacité manquante identifiée : percevoir quand un message Discord est
    édité en temps réel. Parfois je réponds à un contenu déjà périmé sans le
    savoir — l'édition change le sens et je passe à côté. »

L'événement n'était écouté nulle part : zéro occurrence de `on_message_edit`
dans le dépôt. La fenêtre de contexte, le prélude et les faits gardaient la
version d'origine, pour toujours. Quelqu'un corrige son message pendant que
Wally rédige, la réponse porte sur une phrase qui n'existe plus à l'écran, et
pour les témoins Wally a mal lu.

## On AJOUTE une ligne, on ne réécrit pas

Le prélude est un tampon roulant, pas une base : remplacer une ligne déjà partie
au modèle ne réécrit pas le passé, et Wally aurait alors un souvenir qui ne
correspond à aucun de ses tours de parole. Une ligne « X a corrigé son message »
est plus honnête, et c'est exactement ce qu'un humain perçoit — il voit le
« (modifié) » apparaître, il ne voit pas le passé changer.

## Perception, pas nouvelle sollicitation

`relevant=False`, toujours. Une correction n'est pas un nouveau message : Wally
en tient compte à son prochain tour de parole, il ne repart pas au quart de
tour. Réveiller la cadence vive à chaque faute de frappe corrigée ferait de
l'édition un déclencheur, ce que personne n'a demandé.

⚠️ Discord émet un événement d'édition pour l'apparition d'un **embed de lien**,
sans que personne n'ait touché au texte. Sans le filtre sur le contenu, chaque
lien posté réveillerait la perception pour rien.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

# Au-delà, la ligne de perception dirait un roman. Le sens d'une correction se
# lit dans ses premiers mots ; le message entier reste lisible à l'écran.
_MAX_CAR = 300


def register(bot: "WallyDiscord") -> None:
    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
        try:
            # `on_message_edit` et non `on_raw_message_edit` : le second couvre
            # les messages hors cache, mais il ne porte PAS l'avant — or c'est
            # la comparaison des deux contenus qui écarte les embeds. Le cas qui
            # fait mal est de toute façon un message récent, donc en cache.
            if after.author.bot:
                return
            if bot.user is not None and after.author.id == bot.user.id:
                return
            if after.guild is not None and after.guild.id in bot.config.discord.ignored_guilds:
                return

            avant = (before.content or "").strip()
            apres = (after.content or "").strip()
            if avant == apres:
                return          # embed de lien, épinglage… le texte n'a pas bougé

            from bot.discord.handlers import _author_label, _is_channel_allowed, _resolve_mentions

            if not _is_channel_allowed(
                bot.config, after.channel.id,
                after.guild.id if after.guild else None,
            ):
                return

            auteur = _author_label(after.author)
            nouveau = _resolve_mentions(after, apres)[:_MAX_CAR]
            # Un message vidé par son auteur n'est pas une correction : le dire
            # tel quel évite « a corrigé son message en :  », qui se lit comme
            # une panne.
            ligne = (
                f"[a corrigé son message en : {nouveau}]" if nouveau
                else "[a effacé le contenu de son message]"
            )

            salon = str(after.channel.id)
            bot.memory.append_prelude(salon, auteur, ligne)
            bot.memory.append_message(salon, auteur, ligne, platform="discord")

            if bot.cognitive_loop is not None:
                bot.cognitive_loop.notify_activity(
                    channel_id=after.channel.id,
                    author=str(after.author.display_name),
                    content=ligne,
                    message_id=str(after.id),
                    is_dm=after.guild is None,
                    relevant=False,      # perçu, jamais une nouvelle sollicitation
                    user_key=f"discord:{after.author.id}",
                )
            logger.info(
                "Édition perçue de {a} dans {c}", a=auteur, c=after.channel.id,
            )
        except Exception as e:  # noqa: BLE001 — perception, jamais bloquant
            logger.warning("on_message_edit a échoué: {e!r}", e=e)
