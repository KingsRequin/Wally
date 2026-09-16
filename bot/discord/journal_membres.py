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

**Éviter la carte en double sur un ban.** Un membre banni quitte aussi le
serveur : sans précaution, `_carte_depart` publierait un « 🚪 Départ » EN PLUS
du « 🔨 Membre banni ». Se fier au journal d'audit pour repérer ce cas est le
mauvais signal : une permission refusée ou une entrée pas encore écrite après
`_DELAI_AUDIT` (l'audit n'y met pas systématiquement moins de deux secondes)
fait passer un ban pour un départ volontaire, et la carte part quand même en
double — c'est le défaut corrigé ici. `on_member_ban` le dit de PREMIÈRE MAIN,
sans permission à demander : `membre_banni` pose un marqueur en RAM
(`_marquer_banni`) dès l'événement reçu, AVANT tout délai, et `_carte_depart`
le consulte EN PREMIER — trouvé, elle rend la main sans publier, `membre_banni`
portant déjà sa propre carte (raison comprise). Le marqueur expire vite
(`_MARQUEUR_BAN_TTL`, quelques secondes au-delà de `_DELAI_AUDIT`) : passé ce
délai, un départ n'a plus à se taire pour un ban trop ancien pour appartenir à
la même rafale d'événements. Le journal d'audit ne sert plus qu'en SECOURS,
pour distinguer un kick d'un départ volontaire (aucun marqueur équivalent : un
kick n'a pas d'événement `on_member_kick` de première main).

Sens unique : le marqueur n'existe QUE pour faire taire un départ qui n'est
pas encore parti — si la carte de départ est déjà publiée quand l'événement de
ban arrive (ordre inversé, ou délai anormalement long), `membre_banni` publie
quand même la sienne. C'est honnête (un ban a bien eu lieu) au prix d'un
doublon dans ce cas limite, plus rare que celui corrigé ici.

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
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NamedTuple

import discord
from loguru import logger

from bot.core.temps import maintenant
from bot.discord.fiches import borner, fiche, url_avatar
from bot.discord.journal_moderation import (
    ACCENTS_JOURNAL,
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

# Durée de vie du marqueur « banni » posé par `membre_banni` (cf. docstring de
# module, § éviter la carte en double). Large au-delà de `_DELAI_AUDIT` : le
# marqueur doit encore être là quand `_carte_depart` le consulte après SON
# propre délai, même si les deux événements Discord n'arrivent pas dans le
# même ordre exact.
_MARQUEUR_BAN_TTL = 10.0

# Bornage par serveur, même famille que
# `journal_moderation._MAX_COMPTEURS_AUDIT` : sans plafond, un serveur très
# actif ferait croître ce dictionnaire pour la durée de vie du process.
_MAX_MARQUEURS_BAN = 200

# Une raison d'audit n'a AUCUN plafond côté Discord (jusqu'à 512 caractères
# vus en pratique, et rien n'empêche plus). Sur une modification de rôles en
# masse (dashboard), `_ligne_auteur` porte cette raison — bornée ici, plutôt
# qu'un envoi qui dépasse le budget V2 et se perd en silence.
_MAX_RAISON = 300

#: `{guild_id: {user_id: epoch_du_marquage}}`. En RAM seulement — le perdre au
#: redémarrage coûte au pire une carte de départ en double sur un ban survenu
#: juste avant l'arrêt, un cas déjà rare.
_marqueurs_ban: dict[int, "OrderedDict[int, float]"] = {}


def _marquer_banni(guild_id: int, user_id: int, horloge: Callable[[], datetime]) -> None:
    """Pose le marqueur « banni », appelé synchrone dès `on_member_ban` —
    avant tout `await`, pour qu'il existe le plus tôt possible face à un
    départ qui a déjà commencé son propre délai."""
    memoire = _marqueurs_ban.setdefault(guild_id, OrderedDict())
    memoire[user_id] = horloge().timestamp()
    memoire.move_to_end(user_id)
    while len(memoire) > _MAX_MARQUEURS_BAN:
        memoire.popitem(last=False)


def _recemment_banni(guild_id: int, user_id: int, horloge: Callable[[], datetime]) -> bool:
    """Le marqueur « banni » existe-t-il encore pour ce membre, pas expiré ?"""
    memoire = _marqueurs_ban.get(guild_id)
    if not memoire:
        return False
    pose = memoire.get(user_id)
    if pose is None:
        return False
    return horloge().timestamp() - pose < _MARQUEUR_BAN_TTL


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

    La raison n'a pas de plafond côté Discord : bornée à `_MAX_RAISON` AVANT
    l'échappement, pour que la marque de troncature ne porte aucun markdown à
    briser. Sur une modification de rôles en masse (150+ rôles), une raison
    de plusieurs centaines de caractères suffisait à elle seule à dépasser le
    budget V2 de 4000 caractères.
    """
    if not recoupement.lisible or recoupement.entree is None:
        return ""
    modo = getattr(recoupement.entree, "user", None)
    if modo is None:
        return ""   # entrée trouvée mais son auteur n'est plus résolvable
    ligne = f" · **{verbe}** <@{modo.id}>"
    raison = getattr(recoupement.entree, "reason", None)
    if raison:
        raison_bornee = _echapper(discord.utils.escape_markdown(borner(raison, _MAX_RAISON)))
        ligne += f" · **Raison** {raison_bornee}"
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
        meta = (f"**Auteur** <@{member.id}> ({discord.utils.escape_markdown(member.name)}) · "
               f"**Compte créé** {horodatage(member.created_at)}")
        corps = [meta]
        if horloge() - member.created_at < _SEUIL_COMPTE_RECENT:
            corps.append("⚠️ **Compte récent** (moins de 7 jours)")
        vue = fiche("📥 Nouveau membre", corps, accent=ACCENTS_JOURNAL["membre_arrive"],
                    vignette=url_avatar(member), pied=pied_utilisateur(member))
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
        if _recemment_banni(guild_id, user.id, horloge):
            return   # `membre_banni` publie déjà sa propre carte : pas de doublon
        guild = bot.get_guild(guild_id)
        kick = await entree_audit(guild, discord.AuditLogAction.kick, cible_id=user.id, horloge=horloge)
        meta = (f"**Auteur** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Parti** {horodatage(horloge())}")
        rejoint = getattr(user, "joined_at", None)
        if rejoint is not None:
            meta += f" · **Membre depuis** {horodatage(rejoint)}"
        if kick.entree is not None:
            titre = "👢 Membre expulsé"
            meta += _ligne_auteur(kick, "Expulsé par")
            accent = ACCENTS_JOURNAL["membre_expulse"]
        else:
            titre = "🚪 Départ"
            accent = ACCENTS_JOURNAL["membre_parti"]
        vue = fiche(titre, [meta], accent=accent, vignette=url_avatar(user), pied=pied_utilisateur(user))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001 — tâche détachée : personne derrière pour rattraper
        logger.warning("journal des membres : départ non journalisé : {e!r}", e=e)


async def membre_banni(bot: "WallyDiscord", guild: Any, user: Any, *,
                       dormir: Callable[[float], Any] = asyncio.sleep,
                       horloge: Callable[[], datetime] = maintenant) -> None:
    """`on_member_ban` : bannissement, auteur et raison depuis l'audit.

    Pose le marqueur « banni » (`_marquer_banni`) tout de suite, AVANT même
    de savoir si une carte sera publiée (bot exclu, journal désactivé…) : il
    ne sert qu'à faire taire un départ pour CE membre, indépendamment de la
    publication de la carte de ban elle-même.
    """
    try:
        _marquer_banni(guild.id, user.id, horloge)
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
        meta = (f"**Auteur** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Banni** {horodatage(horloge())}{_ligne_auteur(recoupement, 'Banni par')}")
        vue = fiche("🔨 Membre banni", [meta], accent=ACCENTS_JOURNAL["membre_banni"],
                    vignette=url_avatar(user), pied=pied_utilisateur(user))
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
        meta = (f"**Auteur** <@{user.id}> ({discord.utils.escape_markdown(user.name)}) · "
               f"**Débanni** {horodatage(horloge())}{_ligne_auteur(recoupement, 'Débanni par')}")
        vue = fiche("🔓 Membre débanni", [meta], accent=ACCENTS_JOURNAL["membre_debanni"],
                    vignette=url_avatar(user), pied=pied_utilisateur(user))
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

        # `maj`/`roles_maj` peuvent chacune driver PLUSIEURS blocs (nick +
        # exclusion partagent `maj` ; ajoutés + retirés partagent `roles_maj`)
        # — la ligne « Par · Raison » ne se répète qu'à la première utilisation
        # de chaque recoupement, jamais une par bloc. Sans ce partage, une
        # raison d'audit longue sur un changement de rôles en masse (ajoutés
        # ET retirés) doublait son propre poids dans le budget V2.
        ligne_maj = _ligne_auteur(maj, "Par")
        ligne_roles = _ligne_auteur(roles_maj, "Par")

        corps = [f"**Auteur** <@{membre_id}> ({discord.utils.escape_markdown(membre_nom)})"]
        if ch.nick_change:
            avant = _echapper(discord.utils.escape_markdown(ch.nick_avant)) if ch.nick_avant else "*aucun*"
            apres = _echapper(discord.utils.escape_markdown(ch.nick_apres)) if ch.nick_apres else "*aucun*"
            corps.append(f"**Surnom** {avant} → {apres}{ligne_maj}")
            ligne_maj = ""
        if ch.debut_exclusion and ch.exclu_jusqua is not None:
            corps.append(f"**Exclu jusqu'à** {horodatage(ch.exclu_jusqua)}{ligne_maj}")
            ligne_maj = ""
        if ch.fin_exclusion:
            corps.append(f"**Exclusion levée** {horodatage(horloge())}{ligne_maj}")
            ligne_maj = ""
        if ch.ajoutes:
            lignes = borner_lignes([f"- {n}" for n in ch.ajoutes], _MAX_ROLES)
            corps.append(f"**Rôles ajoutés**{ligne_roles}\n{lignes}")
            ligne_roles = ""
        if ch.retires:
            lignes = borner_lignes([f"- {n}" for n in ch.retires], _MAX_ROLES)
            corps.append(f"**Rôles retirés**{ligne_roles}\n{lignes}")
            ligne_roles = ""

        accent = ACCENTS_JOURNAL["membre_exclu"] if ch.debut_exclusion else ACCENTS_JOURNAL["membre_modifie"]
        vue = fiche(_titre_modification(ch), corps, accent=accent, vignette=avatar,
                    pied=pied_utilisateur(SimpleNamespace(id=membre_id)))
        await publier_partout(salons, lambda _t: vue)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal des membres : modification non journalisée : {e!r}", e=e)
