"""Journal vocal — carte unique des salons temporaires + mouvements vocaux.

Suite de `bot/discord/journal_moderation.py`, qui garde les MESSAGES et sert
de tronc commun (`salons_cibles`, `publier_partout`, `horodatage`,
`pied_utilisateur`, `borner_lignes`) au reste du journal de modération.

**Carte vocale unique (#3).** À la création d'un salon vocal temporaire, une
carte est publiée dans chaque salon de logs, et le triplet (salon temporaire,
salon de logs, message) rangé en base (`journal_cartes_vocales`) — un reboot
ne perd rien, il n'y a aucun état en RAM ici. Chaque entrée d'un membre dans
le salon temporaire ajoute son id aux participants de CHAQUE carte. À la
suppression du salon, chaque carte est ÉDITÉE (`message.edit(view=...)`,
message déjà Components V2) plutôt que republiée : durée de vie, créateur,
participants (bornés à `_MAX_PARTICIPANTS` caractères, comme le reste du
journal — cf. `_bloc_participants`). Une carte introuvable (supprimée à la
main dans le salon de logs) republie une carte neuve.

`vocal_cree` (envoi réseau + écriture en base) et `vocal_supprime` partent
tous deux en tâche de fond, indépendamment l'un de l'autre (`_creer()` /
`_supprimer_si_gere()` dans `salons_temporaires.py`) : un salon créé puis
vidé presque aussitôt peut faire lire `vocal_supprime` AVANT que la ligne de
`vocal_cree` existe. `vocal_supprime` attend donc une fois, brièvement,
avant de conclure qu'il n'y a rien à éditer (cf. `_DELAI_RATTRAPAGE`).

Les cartes qu'aucune des deux tâches n'a pu réconcilier (bot arrêté entre la
disparition Discord du salon et l'édition) sont nettoyées au boot par
`nettoyer_cartes_orphelines`, appelée depuis `salons_temporaires.menage_au_boot`.

**Mouvements vocaux (#10).** Depuis `WallyDiscord.on_voice_state_update` :
entrée, sortie, déplacement (avant → après). Ignorés : changements de
mute/sourdine/stream/caméra (même salon), les bots, le salon créateur —
l'aller-retour vers le salon perso serait du bruit, la carte vocale ci-dessus
le couvre déjà.

Remplace `vocal_cree` / `vocal_supprime` de `journal_moderation.py`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord
from loguru import logger

from bot.core.temps import PARIS, maintenant
from bot.discord.fiches import fiche
from bot.discord.journal_moderation import (
    borner_lignes,
    horodatage,
    pied_utilisateur,
    publier_partout,
    salons_cibles,
)

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

_COULEUR_VOCAL = 0x3498DB      # même bleu que l'ancien `vocal_cree`/`vocal_supprime`

# Budget du bloc « Participants », sur les 4000 caractères de TOUS les
# TextDisplay réunis (cf. `bot/discord/fiches.py`). Le reste de la carte
# (titre, créé/supprimé/durée) tient large sous les ~600 caractères restants —
# mesuré avec un nom de salon de 100 caractères (le maximum Discord) et des
# horodatages/mentions au format le plus long.
_MAX_PARTICIPANTS = 3200

# `vocal_cree` (envoi réseau + écriture en base) tourne en parallèle de
# `vocal_supprime` : un salon vidé presque aussitôt après sa création peut
# faire lire la base avant que la ligne existe. Même seam que `_DELAI_AUDIT`
# dans `journal_moderation.py` — `dormir`, injectable, pour ne jamais
# attendre ce délai dans un test.
_DELAI_RATTRAPAGE = 1.0


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


def _bloc_participants(participants: list[int]) -> str:
    """« **Participants** » suivi d'une mention par ligne, bornée.

    Une mention par LIGNE (pas par mot séparé d'espace) : `borner_lignes`
    coupe par unité entière, jamais au milieu d'une mention `<@id>` — sur un
    salon qui a vu passer des centaines de participants, la carte affiche les
    premiers puis une ligne récapitulative « … et N autres » plutôt que de
    dépasser le budget Components V2 (mesuré : 300 participants à 18 chiffres
    dépassent 4000 caractères sans ce bornage).
    """
    mentions = [f"<@{p}>" for p in participants] or ["*aucun*"]
    return f"**Participants**\n{borner_lignes(mentions, _MAX_PARTICIPANTS)}"


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
    meta = (f"**Créé** {horodatage(cree_dt)} par <@{carte['createur_id']}> · "
           f"**Supprimé** {horodatage(supprime_dt)} · **A vécu** {duree}\n"
           f"{_bloc_participants(carte['participants'])}")
    return fiche(f"🔊 {salon.name}", [meta], accent=_COULEUR_VOCAL)


async def vocal_supprime(bot: "WallyDiscord", salon: Any, *,
                         dormir: Callable[[float], Any] = asyncio.sleep) -> None:
    """Salon vocal temporaire supprimé : édite chaque carte de création.

    `vocal_cree` tourne en tâche de fond séparée : sur un salon vidé presque
    aussitôt après sa création, sa ligne peut ne pas encore exister. Une
    absence de ligne déclenche donc UNE relecture après `_DELAI_RATTRAPAGE`
    avant de conclure qu'il n'y a vraiment rien (journal désactivé, ou tous
    les envois de `vocal_cree` avaient échoué).
    """
    try:
        cartes = await bot.db.cartes_vocales(salon.id)
        if not cartes and bot.config.discord.journal_moderation.salon_ids:
            await dormir(_DELAI_RATTRAPAGE)
            cartes = await bot.db.cartes_vocales(salon.id)
        if not cartes:
            logger.info("journal vocal : aucune carte à éditer pour {c} (jamais créée, ou déjà "
                        "supprimée)", c=salon.id)
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


def _vue_orpheline(salon_temp_id: int, carte: dict) -> discord.ui.LayoutView:
    """La carte d'un salon disparu sans que `vocal_supprime` ait pu l'éditer.

    Le salon Discord d'origine n'existe plus (ni en cache, ni via l'API) : ni
    nom, ni heure de suppression exacte à afficher — seule l'édition dit que
    le salon a disparu, sans rien affirmer qu'on ne sait pas.
    """
    cree_dt = datetime.fromtimestamp(carte["cree_a"], tz=PARIS)
    meta = (f"**Créé** {horodatage(cree_dt)} par <@{carte['createur_id']}> · "
           f"**Salon disparu** (détecté au redémarrage, horodatage exact de la suppression perdu)\n"
           f"{_bloc_participants(carte['participants'])}")
    return fiche(f"🔊 Salon {salon_temp_id}", [meta], accent=_COULEUR_VOCAL)


async def _nettoyer_une_carte_orpheline(bot: "WallyDiscord", salon_temp_id: int) -> None:
    try:
        cartes = await bot.db.cartes_vocales(salon_temp_id)
        for carte in cartes:
            salon_log: Any = bot.get_channel(carte["log_salon_id"])
            if salon_log is None:
                continue
            vue = _vue_orpheline(salon_temp_id, carte)
            try:
                message = salon_log.get_partial_message(carte["message_id"])
                await message.edit(view=vue)
            except discord.NotFound:  # la carte a aussi disparu : rien à corriger, juste la ligne à retirer
                pass
            except Exception as e:  # noqa: BLE001 — un salon en échec ne prive pas les autres
                logger.warning("journal vocal : édition de la carte orpheline de {c} impossible : {e!r}",
                               c=salon_temp_id, e=e)
        await bot.db.cartes_vocales_supprimer(salon_temp_id)
        logger.info("journal vocal : carte(s) orpheline(s) nettoyée(s) pour le salon {c}", c=salon_temp_id)
    except Exception as e:  # noqa: BLE001 — un salon en échec ne doit pas arrêter le ménage des autres
        logger.warning("journal vocal : ménage de la carte orpheline de {c} a échoué : {e!r}",
                       c=salon_temp_id, e=e)


async def nettoyer_cartes_orphelines(bot: "WallyDiscord", salons_valides: set[int]) -> None:
    """Édite puis retire les cartes dont le salon temporaire a disparu SANS
    passer par `vocal_supprime` — bot arrêté entre la suppression Discord du
    salon et l'édition de sa carte. Sans ce ménage, la carte reste bloquée
    sur « créé » pour toujours.

    `salons_valides` : le registre `salons_vocaux_temporaires` APRÈS le
    ménage habituel de `menage_au_boot` — tout salon qui a une carte mais
    n'y figure plus est orphelin. Ne lève jamais ; un salon en échec ne prive
    pas les autres.
    """
    try:
        tous = await bot.db.salons_temp_avec_carte()
    except Exception as e:  # noqa: BLE001 — le ménage ne bloque pas le démarrage
        logger.warning("journal vocal : lecture des cartes orphelines impossible : {e!r}", e=e)
        return
    for salon_temp_id in tous - salons_valides:
        await _nettoyer_une_carte_orpheline(bot, salon_temp_id)


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
