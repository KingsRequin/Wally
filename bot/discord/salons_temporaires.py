"""Salons vocaux temporaires — repris du bot Node `wally-discord`.

Entrer dans le salon « créateur » ouvre un salon vocal au nom tiré au sort,
dans la même catégorie, dont l'arrivant reçoit la gestion ; le salon est
supprimé dès qu'il se vide. Le registre en base (`SalonsMixin`) est la seule
chose qui autorise une suppression : un salon vocal ordinaire vide n'est
jamais touché.

⚠️ Appelé depuis `WallyDiscord.on_voice_state_update`, jamais enregistré par
`@bot.event` : un second `on_voice_state_update` REMPLACERAIT la méthode de
classe, et l'accueil vocal de Wally disparaîtrait sans erreur.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_NOM_PAR_DEFAUT = "Nouveau salon"


async def sur_changement_vocal(bot: "WallyDiscord", member: Any, before: Any, after: Any) -> None:
    """Crée ou supprime un salon temporaire. Ne lève jamais."""
    createur = bot.config.discord.salons_temporaires.salon_createur_id
    if createur is None:
        return
    try:
        entre = after.channel is not None and after.channel.id == createur
        venait_du_createur = before.channel is not None and before.channel.id == createur
        if entre and not venait_du_createur and not member.bot:
            await _creer(bot, member, after.channel)
        # Pas de filtre `member.bot` ici : si Wally est le dernier à partir,
        # le salon est vide et doit disparaître comme pour n'importe qui.
        if before.channel is not None and not venait_du_createur and not before.channel.members:
            await _supprimer_si_gere(bot, before.channel)
    except Exception as e:  # noqa: BLE001 — un événement vocal ne fait pas tomber le bot
        logger.warning("salons temporaires : événement vocal non traité : {e!r}", e=e)


async def _creer(bot: "WallyDiscord", member: Any, createur: Any) -> None:
    noms = bot.config.discord.salons_temporaires.noms
    nom = random.choice(noms) if noms else _NOM_PAR_DEFAUT
    salon = await createur.guild.create_voice_channel(
        nom,
        category=createur.category,
        overwrites={member: discord.PermissionOverwrite(manage_channels=True, manage_roles=True)},
        reason="Salon vocal temporaire",
    )
    await bot.db.salon_temporaire_ajouter(salon.id, createur.guild.id)
    try:
        await member.move_to(salon)
    except discord.HTTPException as e:
        # Le membre a quitté le vocal entre l'entrée et le déplacement : le
        # salon ne recevra jamais personne, donc jamais d'événement « vidé ».
        logger.info("salons temporaires : déplacement impossible ({e!r}), salon retiré", e=e)
        await _supprimer(bot, salon)
        return
    logger.info("Salon vocal temporaire « {n} » ({c}) créé pour {m}",
                n=salon.name, c=salon.id, m=member.display_name)


async def _supprimer_si_gere(bot: "WallyDiscord", salon: Any) -> None:
    if salon.id not in await bot.db.salons_temporaires():
        return
    await _supprimer(bot, salon)
    logger.info("Salon vocal temporaire « {n} » ({c}) supprimé (vide)", n=salon.name, c=salon.id)


async def _supprimer(bot: "WallyDiscord", salon: Any) -> None:
    try:
        await salon.delete(reason="Salon vocal temporaire vide")
    except discord.NotFound:
        logger.info("salons temporaires : {c} déjà supprimé", c=salon.id)
    await bot.db.salon_temporaire_retirer(salon.id)


async def menage_au_boot(bot: "WallyDiscord") -> None:
    """Retire les salons vidés ou disparus pendant l'arrêt. Ne lève jamais."""
    if bot.config.discord.salons_temporaires.salon_createur_id is None:
        return
    try:
        for channel_id in await bot.db.salons_temporaires():
            # `bot.get_channel` rend un type large (salon texte, catégorie,
            # DM…) ; seuls les salons vocaux nous intéressent ici, et le
            # registre ne contient jamais autre chose.
            salon: Any = bot.get_channel(channel_id)
            if salon is None:
                await bot.db.salon_temporaire_retirer(channel_id)
                logger.info("salons temporaires : {c} disparu pendant l'arrêt, ligne retirée", c=channel_id)
            elif not salon.members:
                await _supprimer(bot, salon)
                logger.info("salons temporaires : « {n} » vide au boot, supprimé", n=salon.name)
    except Exception as e:  # noqa: BLE001 — le ménage ne bloque pas le démarrage
        logger.warning("salons temporaires : ménage au boot interrompu : {e!r}", e=e)
