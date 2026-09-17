"""Salons vocaux temporaires — repris du bot Node `wally-discord`.

Entrer dans le salon « créateur » ouvre un salon vocal au nom tiré au sort,
dans la même catégorie, dont l'arrivant reçoit la gestion ; le salon est
supprimé dès qu'il se vide. Le registre en base (`SalonsMixin`) est la seule
chose qui autorise une suppression : un salon vocal ordinaire vide n'est
jamais touché.

⚠️ Appelé depuis `WallyDiscord.on_voice_state_update`, jamais enregistré par
`@bot.event` : un second `on_voice_state_update` REMPLACERAIT la méthode de
classe, et l'accueil vocal de Wally disparaîtrait sans erreur.

Les fiches du journal vocal (`bot/discord/journal_vocal.py` — `vocal_cree` /
`vocal_supprime`) partent en tâche de fond (`_fire`) : un envoi lent sur
plusieurs salons de logs ne doit pas retenir le traitement de l'événement
vocal.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_NOM_PAR_DEFAUT = "Nouveau salon"

# Salons dont la suppression est EN COURS. Deux départs quasi simultanés
# passent tous deux la vérification du registre (lecture en base) avant que
# le premier n'ait supprimé quoi que ce soit : sans ce verrou, le second
# supprimait à nouveau (NotFound avalé) puis journalisait et publiait une
# seconde fiche « vocal supprimé ». Rempli AVANT le premier `await`.
_suppressions_en_cours: set[int] = set()


async def sur_changement_vocal(bot: "WallyDiscord", member: Any, before: Any, after: Any) -> None:
    """Crée ou supprime un salon temporaire. Ne lève jamais."""
    createur = bot.config.discord.salons_temporaires.salon_createur_id
    try:
        entre = createur is not None and after.channel is not None and after.channel.id == createur
        venait_du_createur = createur is not None and before.channel is not None and before.channel.id == createur
        if entre and not venait_du_createur and not member.bot:
            await _creer(bot, member, after.channel)
        # Pas de filtre `member.bot` ici : si Wally est le dernier à partir,
        # le salon est vide et doit disparaître comme pour n'importe qui.
        #
        # Et pas de garde « module désactivé » non plus : couper le module
        # arrête la CRÉATION, jamais le ménage. Le registre reste la seule
        # autorisation de supprimer — un salon vocal ordinaire n'y figure pas —,
        # et les salons déjà ouverts au moment de la coupure restaient sinon à
        # vie, à effacer à la main.
        if before.channel is not None and not venait_du_createur and not before.channel.members:
            await _supprimer_si_gere(bot, before.channel)
    except Exception as e:  # noqa: BLE001 — un événement vocal ne fait pas tomber le bot
        logger.warning("salons temporaires : événement vocal non traité : {e!r}", e=e)


async def _creer(bot: "WallyDiscord", member: Any, createur: Any) -> None:
    noms = bot.config.discord.salons_temporaires.noms
    nom = random.choice(noms) if noms else _NOM_PAR_DEFAUT
    try:
        salon = await createur.guild.create_voice_channel(
            nom,
            category=createur.category,
            overwrites={member: discord.PermissionOverwrite(manage_channels=True, manage_roles=True)},
            reason="Salon vocal temporaire",
        )
    except discord.Forbidden as e:
        # Sans ce cas propre, la panne tombait dans le WARNING générique de
        # `sur_changement_vocal`, qui ne dit pas QUOI donner au bot.
        logger.warning("salons temporaires : création refusée sous « {cat} » — permissions "
                       "« Gérer les salons » / « Gérer les rôles » manquantes : {e!r}",
                       cat=getattr(createur.category, "name", None), e=e)
        return
    try:
        await bot.db.salon_temporaire_ajouter(salon.id, createur.guild.id)
    except Exception as e:  # noqa: BLE001 — sans ce retrait, le salon reste ORPHELIN : absent
        # du registre, ni `_supprimer_si_gere` ni `menage_au_boot` ne le verront jamais.
        logger.warning("salons temporaires : enregistrement en base échoué, salon « {n} » ({c}) retiré : {e!r}",
                       n=salon.name, c=salon.id, e=e)
        # Suppression Discord DIRECTE, pas `_supprimer` : la ligne n'a jamais été
        # écrite (la base est justement ce qui vient d'échouer) — la rappeler ici
        # risquerait de masquer la cause déjà journalisée derrière une seconde
        # panne base. `return`, pas `raise` : la panne est déjà journalisée
        # ci-dessus, un second warning générique dans `sur_changement_vocal`
        # serait redondant.
        try:
            await salon.delete(reason="Salon vocal temporaire : enregistrement en base échoué")
        except discord.NotFound:
            logger.info("salons temporaires : {c} déjà supprimé", c=salon.id)
        except Exception as e2:  # noqa: BLE001 — suppression best-effort après une panne déjà journalisée
            logger.warning("salons temporaires : suppression de {c} après panne base a échoué : {e!r}",
                           c=salon.id, e=e2)
        return
    try:
        await member.move_to(salon)
    except discord.Forbidden as e:
        # AVANT `HTTPException`, dont `Forbidden` hérite : une permission
        # manquante n'est pas un membre parti. Sans ce cas, chaque entrée dans
        # le créateur ouvrait puis fermait un salon avec un simple INFO.
        logger.warning("salons temporaires : impossible de déplacer {m} dans « {n} » ({c}) — "
                       "permission « Déplacer des membres » manquante, salon retiré : {e!r}",
                       m=member.display_name, n=salon.name, c=salon.id, e=e)
        await _supprimer(bot, salon)
        return
    except discord.HTTPException as e:
        # Le membre a quitté le vocal entre l'entrée et le déplacement : le
        # salon ne recevra jamais personne, donc jamais d'événement « vidé ».
        logger.info("salons temporaires : déplacement impossible ({e!r}), salon retiré", e=e)
        await _supprimer(bot, salon)
        return
    logger.info("Salon vocal temporaire « {n} » ({c}) créé pour {m}",
                n=salon.name, c=salon.id, m=member.display_name)
    from bot.discord.handlers import _fire
    from bot.discord.journal_vocal import vocal_cree
    _fire(vocal_cree(bot, member, salon))


async def _supprimer_si_gere(bot: "WallyDiscord", salon: Any) -> None:
    if salon.id not in await bot.db.salons_temporaires():
        return
    if not await _supprimer(bot, salon):
        return  # un autre départ l'a supprimé : lui seul journalise et publie la fiche
    logger.info("Salon vocal temporaire « {n} » ({c}) supprimé (vide)", n=salon.name, c=salon.id)
    from bot.discord.handlers import _fire
    from bot.discord.journal_vocal import vocal_supprime
    _fire(vocal_supprime(bot, salon))


async def _supprimer(bot: "WallyDiscord", salon: Any) -> bool:
    """Supprime le salon et sa ligne. True seulement si CET appel l'a supprimé."""
    if salon.id in _suppressions_en_cours:
        return False
    _suppressions_en_cours.add(salon.id)
    try:
        try:
            await salon.delete(reason="Salon vocal temporaire vide")
        except discord.NotFound:
            logger.info("salons temporaires : {c} déjà supprimé", c=salon.id)
            await bot.db.salon_temporaire_retirer(salon.id)
            return False
        await bot.db.salon_temporaire_retirer(salon.id)
        return True
    finally:
        _suppressions_en_cours.discard(salon.id)


async def menage_au_boot(bot: "WallyDiscord") -> None:
    """Retire les salons vidés ou disparus pendant l'arrêt, puis les cartes du
    journal vocal orphelines (salon disparu sans que `vocal_supprime` ait pu
    les éditer — bot arrêté entre-temps). Ne lève jamais.

    Tourne même module DÉSACTIVÉ : ce qui est déjà ouvert doit être rangé, et
    le registre seul autorise une suppression."""
    try:
        registre = await bot.db.salons_temporaires_avec_guild()
    except Exception as e:  # noqa: BLE001 — le ménage ne bloque pas le démarrage
        logger.warning("salons temporaires : ménage au boot interrompu : {e!r}", e=e)
        return
    for channel_id, guild_id in registre.items():
        try:
            # `bot.get_channel` rend un type large (salon texte, catégorie,
            # DM…) ; seuls les salons vocaux nous intéressent ici, et le
            # registre ne contient jamais autre chose.
            salon: Any = bot.get_channel(channel_id)
            if salon is None:
                await _verifier_hors_cache(bot, channel_id, guild_id)
            elif not salon.members:
                if await _supprimer(bot, salon):
                    logger.info("salons temporaires : « {n} » vide au boot, supprimé", n=salon.name)
        except Exception as e:  # noqa: BLE001 — un salon en échec ne doit pas arrêter le ménage des autres
            logger.warning("salons temporaires : {c} : ménage échoué : {e!r}", c=channel_id, e=e)

    from bot.discord.journal_vocal import nettoyer_cartes_orphelines
    try:
        restants = await bot.db.salons_temporaires()
    except Exception as e:  # noqa: BLE001 — le ménage des cartes ne bloque pas le démarrage
        logger.warning("salons temporaires : lecture du registre pour les cartes orphelines a échoué : {e!r}",
                       e=e)
        return
    await nettoyer_cartes_orphelines(bot, restants)


async def _verifier_hors_cache(bot: "WallyDiscord", channel_id: int, guild_id: int) -> None:
    """Un salon absent du cache n'est PAS forcément disparu.

    Pendant une panne ou une reconnexion, un serveur indisponible n'a aucun
    salon en cache : retirer la ligne sur ce seul indice rendait ORPHELIN un
    salon bien réel, que plus rien ne supprimerait jamais. Deux preuves de
    disparition seulement : un `NotFound` de l'API, ou un `Forbidden` alors
    que Wally n'est plus du tout dans le serveur (expulsé : l'API répond 403
    « Missing Access », jamais 404, et la ligne resterait pour toujours).
    Tout le reste garde la ligne pour le prochain boot.
    """
    try:
        await bot.fetch_channel(channel_id)
    except discord.NotFound:
        await bot.db.salon_temporaire_retirer(channel_id)
        logger.info("salons temporaires : {c} disparu pendant l'arrêt, ligne retirée", c=channel_id)
        return
    except discord.Forbidden as e:
        if bot.get_guild(guild_id) is None:
            await bot.db.salon_temporaire_retirer(channel_id)
            logger.info("salons temporaires : {c} inaccessible, Wally n'est plus dans le serveur {g}, "
                        "ligne retirée", c=channel_id, g=guild_id)
            return
        logger.info("salons temporaires : {c} invérifiable au boot ({e!r}), ligne gardée", c=channel_id, e=e)
        return
    except Exception as e:  # noqa: BLE001 — invérifiable : la ligne reste, retentée au prochain boot
        logger.info("salons temporaires : {c} invérifiable au boot ({e!r}), ligne gardée", c=channel_id, e=e)
        return
    logger.info("salons temporaires : {c} existe mais hors cache (serveur indisponible ?), ligne gardée",
                c=channel_id)
