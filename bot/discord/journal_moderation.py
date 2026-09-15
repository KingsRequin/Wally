"""Journal de modération — repris du bot Node `wally-discord`.

Un embed par geste dans le salon de logs : message supprimé, message modifié,
salon vocal temporaire créé ou supprimé. C'est un outil de MODÉRATION, pas de
la perception : il couvre aussi les messages de bots et les serveurs que la
perception de Wally ignore (`ignored_guilds`).

Les `@` sont neutralisés ET les mentions coupées : un message supprimé qui
contenait `@everyone` ne doit pas notifier le serveur une seconde fois.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_MESSAGE = 0xE67E22
_COULEUR_VOCAL = 0x3498DB
_MAX_CHAMP = 1024          # limite Discord d'une valeur de champ


def _echapper(texte: str) -> str:
    return texte.replace("@", "@\u200b")


async def _publier(bot: "WallyDiscord", guild_id: int | None, *, titre: str, description: str,
                   couleur: int, champs: list[tuple[str, str, bool]], pied: str | None = None) -> None:
    cfg = bot.config.discord.journal_moderation
    if cfg.salon_id is None or guild_id not in cfg.guild_ids:
        return
    # `bot.get_channel` rend un type large (salon texte, catégorie, DM…) ; le
    # salon de logs est configuré par l'owner comme un salon textuel.
    salon: Any = bot.get_channel(cfg.salon_id)
    if salon is None:
        logger.warning("journal de modération : salon {c} introuvable", c=cfg.salon_id)
        return
    embed = discord.Embed(description=description, colour=couleur, timestamp=discord.utils.utcnow())
    embed.set_author(name=titre)
    for nom, valeur, en_ligne in champs:
        embed.add_field(name=nom, value=(valeur or "[vide]")[:_MAX_CHAMP], inline=en_ligne)
    if pied:
        embed.set_footer(text=pied)
    try:
        await salon.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:  # noqa: BLE001 — un journal ne casse pas ce qu'il observe
        logger.warning("journal de modération : envoi impossible dans {c} : {e!r}", c=cfg.salon_id, e=e)


async def message_supprime(bot: "WallyDiscord", payload: Any) -> None:
    try:
        msg = payload.cached_message
        salon = bot.get_channel(payload.channel_id)
        nom_salon = getattr(salon, "name", "inconnu")
        auteur = msg.author.name if msg is not None else "inconnu"
        contenu = _echapper(msg.content) if msg is not None and msg.content.strip() else "[contenu non disponible]"
        champs = [("Auteur", auteur, True), ("Salon", f"#{nom_salon}", True),
                  ("ID Message", str(payload.message_id), True), ("Contenu", contenu, False)]
        pieces = list(msg.attachments) if msg is not None else []
        if pieces:
            champs.append((f"Pièces jointes ({len(pieces)})",
                           "\n".join(p.filename or p.url for p in pieces), False))
        await _publier(bot, payload.guild_id, titre="🗑️ Message supprimé",
                       description=f"Message supprimé dans <#{payload.channel_id}>",
                       couleur=_COULEUR_MESSAGE, champs=champs, pied=f"Auteur: {auteur}")
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : suppression non journalisée : {e!r}", e=e)


async def message_modifie(bot: "WallyDiscord", before: Any, after: Any) -> None:
    try:
        if after.author.bot:
            return
        avant, apres = before.content or "", after.content or ""
        if avant == apres:
            return          # embed de lien, épinglage : le texte n'a pas bougé
        auteur = after.author.name
        guild_id = after.guild.id if after.guild is not None else None
        await _publier(bot, guild_id, titre="✏️ Message modifié",
                       description=f"Message modifié dans <#{after.channel.id}>",
                       couleur=_COULEUR_MESSAGE, pied=f"Auteur: {auteur}",
                       champs=[("Auteur", auteur, True), ("Salon", f"#{after.channel.name}", True),
                               ("ID Message", str(after.id), True),
                               ("Avant", _echapper(avant), False), ("Après", _echapper(apres), False)])
    except Exception as e:  # noqa: BLE001
        logger.warning("journal de modération : modification non journalisée : {e!r}", e=e)


async def vocal_cree(bot: "WallyDiscord", member: Any, salon: Any) -> None:
    await _publier(bot, salon.guild.id, titre="🔊 Canal vocal créé",
                   description=f"Canal **{salon.name}** créé", couleur=_COULEUR_VOCAL,
                   champs=[("Utilisateur", member.name, True), ("Canal", salon.name, True),
                           ("ID", str(salon.id), True)])


async def vocal_supprime(bot: "WallyDiscord", salon: Any) -> None:
    await _publier(bot, salon.guild.id, titre="🔇 Canal vocal supprimé",
                   description=f"Canal **{salon.name}** supprimé (vide)", couleur=_COULEUR_VOCAL,
                   champs=[("Canal", salon.name, True), ("ID", str(salon.id), True)])
