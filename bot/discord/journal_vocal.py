"""Journal vocal — carte unique des salons temporaires + mouvements vocaux.

Suite de `bot/discord/journal_moderation.py`, qui garde les MESSAGES et sert
de tronc commun (`salons_cibles`, `publier_partout`, `horodatage`,
`pied_utilisateur`) au reste du journal de modération.

**Carte vocale unique (#3).** À la création d'un salon vocal temporaire, une
carte est publiée dans chaque salon de logs, et le triplet (salon temporaire,
salon de logs, message) rangé en base (`journal_cartes_vocales`) — un reboot
ne perd rien, il n'y a aucun état en RAM ici. Chaque entrée d'un membre dans
le salon temporaire ajoute son id aux participants de CHAQUE carte. À la
suppression du salon, chaque carte est ÉDITÉE (`message.edit(view=...)`,
message déjà Components V2) plutôt que republiée : durée de vie, créateur,
participants. Une carte introuvable (supprimée à la main dans le salon de
logs) republie une carte neuve — l'information ne doit pas se perdre parce
que l'édition a échoué.

**Mouvements vocaux (#10).** Depuis `WallyDiscord.on_voice_state_update` :
entrée, sortie, déplacement (avant → après). Ignorés : changements de
mute/sourdine/stream/caméra (même salon), les bots, le salon créateur —
l'aller-retour vers le salon perso serait du bruit, la carte vocale ci-dessus
le couvre déjà.

Remplace `vocal_cree` / `vocal_supprime` de `journal_moderation.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

from bot.core.temps import PARIS, maintenant
from bot.discord.fiches import fiche
from bot.discord.journal_moderation import horodatage, pied_utilisateur, publier_partout, salons_cibles

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_VOCAL = 0x3498DB      # même bleu que l'ancien `vocal_cree`/`vocal_supprime`


def _duree(secondes: float) -> str:
    """Une durée en clair : « 45 s », « 3 min », « 1 h 12 min »."""
    total = max(int(secondes), 0)
    heures, reste = divmod(total, 3600)
    minutes, secs = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    return f"{secs} s"


async def vocal_cree(bot: "WallyDiscord", member: Any, salon: Any) -> None:
    """Salon vocal temporaire créé : une carte par salon de logs, rangée en
    base pour être éditée (et non republiée) à la suppression."""
    try:
        cibles = salons_cibles(bot, salon.guild.id, None)
        if not cibles:
            return
        meta = (f"**Par** <@{member.id}> · **Salon** {salon.name} · **ID** {salon.id} · "
               f"**Créé** {horodatage(maintenant())}")
        vue = fiche("🔊 Canal vocal créé", [meta], accent=_COULEUR_VOCAL, pied=pied_utilisateur(member))
        for salon_log in cibles:
            try:
                message = await salon_log.send(view=vue, allowed_mentions=discord.AllowedMentions.none())
            except Exception as e:  # noqa: BLE001 — un salon en échec ne prive pas les autres
                logger.warning("journal vocal : envoi impossible dans {c} : {e!r}",
                               c=getattr(salon_log, "id", "?"), e=e)
                continue
            await bot.db.carte_vocale_ajouter(salon.id, salon_log.id, message.id, member.id, [member.id])
    except Exception as e:  # noqa: BLE001 — jamais lever, appelé depuis salons_temporaires
        logger.warning("journal vocal : création non journalisée : {e!r}", e=e)


def _vue_supprimee(salon: Any, carte: dict, supprime_a: float) -> discord.ui.LayoutView:
    duree = _duree(supprime_a - carte["cree_a"])
    cree_dt = datetime.fromtimestamp(carte["cree_a"], tz=PARIS)
    supprime_dt = datetime.fromtimestamp(supprime_a, tz=PARIS)
    participants = " ".join(f"<@{p}>" for p in carte["participants"]) or "*aucun*"
    meta = (f"**Créé** {horodatage(cree_dt)} par <@{carte['createur_id']}> · "
           f"**Supprimé** {horodatage(supprime_dt)} · **A vécu** {duree}\n"
           f"**Participants** {participants}")
    return fiche(f"🔊 {salon.name}", [meta], accent=_COULEUR_VOCAL)


async def vocal_supprime(bot: "WallyDiscord", salon: Any) -> None:
    """Salon vocal temporaire supprimé : édite chaque carte de création.

    Sans ligne en base pour ce salon (création non journalisée : journal
    désactivé, ou tous les envois avaient échoué), rien à éditer.
    """
    try:
        cartes = await bot.db.cartes_vocales(salon.id)
        if not cartes:
            return
        supprime_a = maintenant().timestamp()
        for carte in cartes:
            salon_log: Any = bot.get_channel(carte["log_salon_id"])
            if salon_log is None:
                logger.warning("journal vocal : salon de logs {c} introuvable, carte non éditée",
                               c=carte["log_salon_id"])
                continue
            vue = _vue_supprimee(salon, carte, supprime_a)
            try:
                message = salon_log.get_partial_message(carte["message_id"])
                await message.edit(view=vue)
            except discord.NotFound:
                try:
                    await salon_log.send(view=vue, allowed_mentions=discord.AllowedMentions.none())
                except Exception as e:  # noqa: BLE001 — un salon en échec ne prive pas les autres
                    logger.warning("journal vocal : nouvelle carte impossible dans {c} : {e!r}",
                                   c=carte["log_salon_id"], e=e)
            except Exception as e:  # noqa: BLE001 — un salon en échec ne prive pas les autres
                logger.warning("journal vocal : édition impossible dans {c} : {e!r}",
                               c=carte["log_salon_id"], e=e)
        await bot.db.cartes_vocales_supprimer(salon.id)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal vocal : suppression non journalisée : {e!r}", e=e)


async def mouvement_vocal(bot: "WallyDiscord", member: Any, before: Any, after: Any) -> None:
    """Entrée, sortie ou déplacement vocal : une fiche courte par mouvement.

    Ignorés : mute/sourdine/stream/caméra (même salon des deux côtés), les
    bots, le salon créateur (`vocal_cree`/`vocal_supprime` couvrent déjà
    l'aller-retour vers le salon perso — le republier serait du bruit).
    """
    try:
        if member.bot:
            return
        avant, apres = before.channel, after.channel
        avant_id = getattr(avant, "id", None)
        apres_id = getattr(apres, "id", None)
        if avant_id == apres_id:
            return
        createur = bot.config.discord.salons_temporaires.salon_createur_id
        if createur is not None and createur in (avant_id, apres_id):
            return
        if apres_id is not None:
            await bot.db.carte_vocale_participant_ajouter(apres_id, member.id)
        guild = (apres or avant).guild
        cibles = salons_cibles(bot, guild.id, None)
        if not cibles:
            return
        quand = horodatage(maintenant())
        if avant is None:
            titre = "🔊 Entrée vocale"
            corps = f"**Qui** <@{member.id}> · **Salon** {apres.mention} · **Entré** {quand}"
        elif apres is None:
            titre = "🔇 Sortie vocale"
            corps = f"**Qui** <@{member.id}> · **Salon** {avant.mention} · **Sorti** {quand}"
        else:
            titre = "↔️ Déplacement vocal"
            corps = f"**Qui** <@{member.id}> · **De** {avant.mention} · **Vers** {apres.mention} · **Déplacé** {quand}"
        vue = fiche(titre, [corps], accent=_COULEUR_VOCAL, pied=pied_utilisateur(member))
        await publier_partout(cibles, lambda _t: vue)
    except Exception as e:  # noqa: BLE001 — un mouvement vocal ne fait pas tomber le bot
        logger.warning("journal vocal : mouvement non journalisé : {e!r}", e=e)
