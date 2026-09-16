"""Journal des membres — arrivées, départs, sanctions, surnoms et rôles.

Suite de `bot/discord/journal_moderation.py`, qui garde les MESSAGES et sert de
tronc commun (`salons_cibles`, `publier_partout`, `horodatage`,
`pied_utilisateur`, `borner_lignes`, `entree_audit`) au reste du journal de
modération.

**#8 Membres.** Arrivée (`membre_rejoint`) : âge du compte, badge ⚠️ si moins
de 7 jours. Départ (`membre_parti`, `on_raw_member_remove` — le membre peut
être hors cache) : distingue une expulsion (entrée d'audit `kick` récente sur
ce membre) d'un départ volontaire ; durée de présence si `joined_at` connu.
Ban (`membre_banni`) / déban (`membre_debanni`) : auteur et raison depuis
l'audit, même recoupement que #1 (T2).

**Éviter la carte en double sur un ban.** Discord dispatche TOUJOURS
`GUILD_BAN_ADD` avant `GUILD_MEMBER_REMOVE` (le membre banni quitte donc
aussi le serveur) : sans précaution, un ban publierait à la fois une carte
« départ » et une carte « banni ». `_carte_depart` attend `_DELAI_AUDIT` avant
de conclure (comme #1), et vérifie D'ABORD une entrée `ban` récente sur ce
membre — trouvée, elle rend la main sans publier : `membre_banni` porte déjà
sa propre carte, plus complète (raison comprise). Aucun état partagé entre
les deux tâches : chacune relit le journal d'audit, qui a eu le temps de
s'écrire pendant l'attente commune.

**#9 Surnoms et rôles.** `membre_modifie` (`on_member_update`, UN SEUL dans
`bot/` — il porte #8 « exclusion temporaire » et #9 ensemble) : surnom changé
(avant → après), rôles ajoutés/retirés (diff d'ensembles, noms), exclusion
temporaire posée ou levée (`timed_out_until` qui passe de/vers `None`).
Auteur (et raison) via l'audit `member_update` (surnom, exclusion) ou
`member_role_update` (rôles) si trouvé. `on_user_update` (members.py, pseudo
de COMPTE) n'est pas concerné.

**#4 Bots.** `JournalModerationConfig.inclure_bots` s'applique à tous les
événements de ce module, comme au reste du journal : Wally lui-même compte
comme un bot.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NamedTuple

import discord
from loguru import logger

from bot.core.temps import maintenant
from bot.discord.fiches import ACCENT_ALERTE, ACCENT_NEUTRE, ACCENT_OK, fiche, url_avatar
from bot.discord.journal_moderation import (
    Recoupement,
    borner_lignes,
    entree_audit,
    horodatage,
    pied_utilisateur,
    publier_partout,
    salons_cibles,
)

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

# Discord n'écrit pas dans l'audit à l'instant du geste — même délai que #1
# (`journal_moderation._DELAI_AUDIT`), constante propre à ce module plutôt
# qu'importée : chaque tronçon du journal garde son propre délai, comme
# `journal_vocal._DELAI_RATTRAPAGE`.
_DELAI_AUDIT = 2.0

# Budget d'un bloc « Rôles ajoutés »/« Rôles retirés », sur les 4000 caractères
# de TOUS les TextDisplay réunis (cf. `bot/discord/fiches.py`). Un rôle pèse au
# plus 100 caractères (plafond Discord) : 100+ rôles changés d'un coup (édition
# en masse via le dashboard) dépassent largement le budget sans ce bornage.
_MAX_ROLES = 1500

# Un compte plus jeune que ça porte le badge « compte récent » à l'arrivée.
_SEUIL_COMPTE_RECENT = timedelta(days=7)


def _echapper(texte: str) -> str:
    """Neutralise un `@` littéral, comme `journal_moderation._echapper`.

    Fonction locale plutôt qu'importée : `_echapper` y est privée, et cette
    version-ci n'a besoin que d'un seul geste (surnom, raison d'audit) —
    dupliquer une ligne coûte moins qu'exposer une brique interne d'un autre
    module.
    """
    return texte.replace("@", "@\u200b")


def _ligne_auteur(recoupement: Recoupement, verbe: str) -> str:
    """Le fragment optionnel « · **{verbe}** <@modo>[ · **Raison** …] ».

    Contrairement à `journal_moderation._ligne_supprime_par` (suppression de
    message, où l'ABSENCE d'entrée est en soi une information — Discord ne
    trace jamais l'auteur ni un bot), les actions couvertes ici (kick, ban,
    déban, modification de membre) sont TOUJOURS journalisées par Discord :
    une entrée manquante ne dit rien de fiable, donc aucune ligne n'est
    ajoutée plutôt que d'affirmer une absence.
    """
    if not recoupement.lisible or recoupement.entree is None:
        return ""
    modo = getattr(recoupement.entree, "user", None)
    if modo is None:
        return ""   # entrée trouvée mais son auteur n'est plus résolvable
    ligne = f" · **{verbe}** <@{modo.id}>"
    raison = getattr(recoupement.entree, "reason", None)
    if raison:
        ligne += f" · **Raison** {_echapper(discord.utils.escape_markdown(raison))}"
    return ligne


def _timeout_actif(membre: Any, horloge: Callable[[], datetime]) -> bool:
    """`timed_out_until` vaut parfois une date PASSÉE quand l'exclusion a
    expiré d'elle-même : seule une date FUTURE compte comme active."""
    jusqua = getattr(membre, "timed_out_until", None)
    return jusqua is not None and jusqua > horloge()


async def membre_rejoint(bot: "WallyDiscord", member: Any, *,
                         horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_member_join` (appelé en tâche de fond depuis `events/members.py`) :
    la carte d'un nouveau membre, âge du compte et badge « compte récent »."""
    try:
        cfg = bot.config.discord.journal_moderation
        if member.bot and not cfg.inclure_bots:
            return
        salons = salons_cibles(bot, member.guild.id, None)
        if not salons:
            return
        meta = (f"**Qui** <@{member.id}> ({discord.utils.escape_markdown(member.name)}) · "
               f"**Compte créé** {horodatage(member.created_at)}")
        corps = [meta]
        if horloge() - member.created_at < _SEUIL_COMPTE_RECENT:
            corps.append("⚠️ **Compte récent** (moins de 7 jours)")
        vue = fiche("📥 Nouveau membre", corps, accent=ACCENT_OK, vignette=url_avatar(member),
                    pied=pied_utilisateur(member))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : arrivée non journalisée : {e!r}", e=e)


async def membre_parti(bot: "WallyDiscord", payload: Any, *,
                       dormir: Callable[[float], Any] = asyncio.sleep,
                       horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_raw_member_remove` : départ, en tâche de fond (délai d'audit).

    Brut (`raw`) : un membre qui a quitté un serveur où il n'était pas en
    cache doit quand même être journalisé — `payload.user` est alors un
    `discord.User` simple (pas de `joined_at`).
    """
    try:
        cfg = bot.config.discord.journal_moderation
        user = payload.user
        if user.bot and not cfg.inclure_bots:
            return
        salons = salons_cibles(bot, payload.guild_id, None)
        if not salons:
            return
        from bot.discord.handlers import _fire
        _fire(_carte_depart(bot, payload.guild_id, user, salons, dormir=dormir, horloge=horloge))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : départ non journalisé : {e!r}", e=e)


async def _carte_depart(bot: "WallyDiscord", guild_id: int, user: Any, salons: list[Any], *,
                        dormir: Callable[[float], Any], horloge: Callable[[], datetime]) -> None:
    try:
        await dormir(_DELAI_AUDIT)
        guild = bot.get_guild(guild_id)
        ban = await entree_audit(guild, discord.AuditLogAction.ban, cible_id=user.id, horloge=horloge)
        if ban.entree is not None:
            return   # `membre_banni` publie déjà sa propre carte : pas de doublon
        kick = await entree_audit(guild, discord.AuditLogAction.kick, cible_id=user.id, horloge=horloge)
        meta = (f"**Qui** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Parti** {horodatage(horloge())}")
        rejoint = getattr(user, "joined_at", None)
        if rejoint is not None:
            meta += f" · **Membre depuis** {horodatage(rejoint)}"
        if kick.entree is not None:
            titre = "👢 Membre expulsé"
            meta += _ligne_auteur(kick, "Expulsé par")
            accent = ACCENT_ALERTE
        else:
            titre = "🚪 Départ"
            accent = ACCENT_NEUTRE
        vue = fiche(titre, [meta], accent=accent, vignette=url_avatar(user), pied=pied_utilisateur(user))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001 — tâche détachée : personne derrière pour rattraper
        logger.warning("journal des membres : départ non journalisé : {e!r}", e=e)


async def membre_banni(bot: "WallyDiscord", guild: Any, user: Any, *,
                       dormir: Callable[[float], Any] = asyncio.sleep,
                       horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_member_ban` : bannissement, auteur et raison depuis l'audit."""
    try:
        cfg = bot.config.discord.journal_moderation
        if user.bot and not cfg.inclure_bots:
            return
        salons = salons_cibles(bot, guild.id, None)
        if not salons:
            return
        from bot.discord.handlers import _fire
        _fire(_carte_ban(bot, guild, user, salons, dormir=dormir, horloge=horloge))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : ban non journalisé : {e!r}", e=e)


async def _carte_ban(bot: "WallyDiscord", guild: Any, user: Any, salons: list[Any], *,
                     dormir: Callable[[float], Any], horloge: Callable[[], datetime]) -> None:
    try:
        await dormir(_DELAI_AUDIT)
        recoupement = await entree_audit(guild, discord.AuditLogAction.ban, cible_id=user.id, horloge=horloge)
        meta = (f"**Qui** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Banni** {horodatage(horloge())}{_ligne_auteur(recoupement, 'Banni par')}")
        vue = fiche("🔨 Membre banni", [meta], accent=ACCENT_ALERTE, vignette=url_avatar(user),
                    pied=pied_utilisateur(user))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : ban non journalisé : {e!r}", e=e)


async def membre_debanni(bot: "WallyDiscord", guild: Any, user: Any, *,
                         dormir: Callable[[float], Any] = asyncio.sleep,
                         horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_member_unban` : déban, auteur depuis l'audit."""
    try:
        cfg = bot.config.discord.journal_moderation
        if user.bot and not cfg.inclure_bots:
            return
        salons = salons_cibles(bot, guild.id, None)
        if not salons:
            return
        from bot.discord.handlers import _fire
        _fire(_carte_deban(bot, guild, user, salons, dormir=dormir, horloge=horloge))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : déban non journalisé : {e!r}", e=e)


async def _carte_deban(bot: "WallyDiscord", guild: Any, user: Any, salons: list[Any], *,
                       dormir: Callable[[float], Any], horloge: Callable[[], datetime]) -> None:
    try:
        await dormir(_DELAI_AUDIT)
        recoupement = await entree_audit(guild, discord.AuditLogAction.unban, cible_id=user.id, horloge=horloge)
        meta = (f"**Qui** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Débanni** {horodatage(horloge())}{_ligne_auteur(recoupement, 'Débanni par')}")
        vue = fiche("🔓 Membre débanni", [meta], accent=ACCENT_OK, vignette=url_avatar(user),
                    pied=pied_utilisateur(user))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : déban non journalisé : {e!r}", e=e)


class _Changements(NamedTuple):
    """Ce qui a changé sur un `on_member_update`, capturé AVANT l'attente
    d'audit : `after` continue de vivre (discord.py le mute en place), le
    relire après `_DELAI_AUDIT` risquerait de décrire un état plus récent
    que celui qui a déclenché CET événement."""
    nick_change: bool
    nick_avant: str | None
    nick_apres: str | None
    debut_exclusion: bool
    fin_exclusion: bool
    exclu_jusqua: datetime | None
    ajoutes: list[str]
    retires: list[str]

    @property
    def vide(self) -> bool:
        return not (self.nick_change or self.debut_exclusion or self.fin_exclusion
                    or self.ajoutes or self.retires)


def _titre_modification(ch: _Changements) -> str:
    """Un titre précis quand un seul aspect a changé ; générique sinon — un
    `on_member_update` peut porter plusieurs changements à la fois (édition
    groupée depuis le dashboard)."""
    aspects = sum((ch.nick_change, ch.debut_exclusion or ch.fin_exclusion,
                   bool(ch.ajoutes or ch.retires)))
    if aspects > 1:
        return "🔧 Membre modifié"
    if ch.nick_change:
        return "✏️ Surnom modifié"
    if ch.debut_exclusion:
        return "⏳ Exclusion temporaire"
    if ch.fin_exclusion:
        return "✅ Exclusion levée"
    return "🎭 Rôles modifiés"


async def membre_modifie(bot: "WallyDiscord", before: Any, after: Any, *,
                         dormir: Callable[[float], Any] = asyncio.sleep,
                         horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_member_update`, UN SEUL dans `bot/` : porte #8 (exclusion
    temporaire) et #9 (surnom, rôles) ensemble."""
    try:
        cfg = bot.config.discord.journal_moderation
        if after.bot and not cfg.inclure_bots:
            return
        nick_change = before.nick != after.nick
        avant_actif = _timeout_actif(before, horloge)
        apres_actif = _timeout_actif(after, horloge)
        avant_ids = {r.id for r in before.roles}
        apres_ids = {r.id for r in after.roles}
        ch = _Changements(
            nick_change=nick_change,
            nick_avant=before.nick if nick_change else None,
            nick_apres=after.nick if nick_change else None,
            debut_exclusion=not avant_actif and apres_actif,
            fin_exclusion=avant_actif and not apres_actif,
            exclu_jusqua=after.timed_out_until if (not avant_actif and apres_actif) else None,
            ajoutes=[discord.utils.escape_markdown(r.name) for r in after.roles if r.id not in avant_ids],
            retires=[discord.utils.escape_markdown(r.name) for r in before.roles if r.id not in apres_ids],
        )
        if ch.vide:
            return   # avatar, statut de boost… rien que ce module journalise
        salons = salons_cibles(bot, after.guild.id, None)
        if not salons:
            return
        from bot.discord.handlers import _fire
        _fire(_carte_modification(bot, guild_id=after.guild.id, membre_id=after.id,
                                  membre_nom=after.name, avatar=url_avatar(after), salons=salons,
                                  ch=ch, dormir=dormir, horloge=horloge))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : modification non journalisée : {e!r}", e=e)


async def _carte_modification(bot: "WallyDiscord", *, guild_id: int, membre_id: int, membre_nom: str,
                              avatar: str | None, salons: list[Any], ch: _Changements,
                              dormir: Callable[[float], Any], horloge: Callable[[], datetime]) -> None:
    try:
        await dormir(_DELAI_AUDIT)
        guild = bot.get_guild(guild_id)
        # Sentinelle « rien à dire » : évite un `Recoupement | None` — les
        # branches ci-dessous ne lisent `maj`/`roles_maj` que lorsque la
        # condition qui a déclenché leur calcul est elle-même vraie.
        maj = roles_maj = Recoupement(None, True)
        if ch.nick_change or ch.debut_exclusion or ch.fin_exclusion:
            maj = await entree_audit(guild, discord.AuditLogAction.member_update,
                                     cible_id=membre_id, horloge=horloge)
        if ch.ajoutes or ch.retires:
            roles_maj = await entree_audit(guild, discord.AuditLogAction.member_role_update,
                                           cible_id=membre_id, horloge=horloge)

        corps = [f"**Qui** <@{membre_id}> ({discord.utils.escape_markdown(membre_nom)})"]
        if ch.nick_change:
            avant = _echapper(discord.utils.escape_markdown(ch.nick_avant)) if ch.nick_avant else "*aucun*"
            apres = _echapper(discord.utils.escape_markdown(ch.nick_apres)) if ch.nick_apres else "*aucun*"
            corps.append(f"**Surnom** {avant} → {apres}{_ligne_auteur(maj, 'Par')}")
        if ch.debut_exclusion and ch.exclu_jusqua is not None:
            corps.append(f"**Exclu jusqu'à** {horodatage(ch.exclu_jusqua)}{_ligne_auteur(maj, 'Par')}")
        if ch.fin_exclusion:
            corps.append(f"**Exclusion levée** {horodatage(horloge())}{_ligne_auteur(maj, 'Par')}")
        if ch.ajoutes:
            lignes = borner_lignes([f"- {n}" for n in ch.ajoutes], _MAX_ROLES)
            corps.append(f"**Rôles ajoutés**{_ligne_auteur(roles_maj, 'Par')}\n{lignes}")
        if ch.retires:
            lignes = borner_lignes([f"- {n}" for n in ch.retires], _MAX_ROLES)
            corps.append(f"**Rôles retirés**{_ligne_auteur(roles_maj, 'Par')}\n{lignes}")

        accent = ACCENT_ALERTE if ch.debut_exclusion else (ACCENT_OK if ch.fin_exclusion else ACCENT_NEUTRE)
        vue = fiche(_titre_modification(ch), corps, accent=accent, vignette=avatar,
                    pied=pied_utilisateur(SimpleNamespace(id=membre_id)))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : modification non journalisée : {e!r}", e=e)
