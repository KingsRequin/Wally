# bot/discord/commands/meme_masse.py
"""Importer des memes en MASSE : ratisser un salon, ou ranger au fil de l'eau.

Le chemin unitaire (`meme_cmd`) montre un aperçu et attend un clic. À trois
cents images, cet aperçu n'a plus de sens : ici on décrit et on range d'un
trait, et c'est le RAPPORT qui rend des comptes — un embed PUBLIC posté dans le
salon, parce que la banque ainsi gonflée est celle que tout le monde verra
défiler sur l'overlay.

Deux invariants tiennent tout le module :

- **Dédoublonner avant de décrire.** La vision coûte un appel facturé et deux à
  cinq secondes par image. La moitié d'un salon de memes est du déjà-vu ; la
  décrire d'abord double la facture et la durée pour des fichiers qu'on jette.
- **Un lot, une session.** `meme_import.SessionImport` lit l'index du dossier
  une fois. Sans elle, chaque image relirait les 44 Mo de la banque, et deux
  imports simultanés tireraient le même numéro de fichier.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Sequence

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.core import meme_import
from bot.core.memes import _EXTENSIONS_MEDIA
from bot.core.temps import PARIS
from bot.discord.commands.meme_cmd import (
    DOSSIER_MEMES,
    _MAX_CONTENU,
    decrire_image,
    images_du_message,
    telecharger,
)

PARIS = PARIS
# L'application raisonne en Europe/Paris alors que l'hôte est en UTC : lire une
# date en naïf ferait commencer « le 1er août » à 2 h du matin.
_DUREE = re.compile(r"^(\d+)\s*([jhd])$", re.IGNORECASE)

# Ce qu'un seul appel accepte de ratisser. Le plafond n'est pas une facture mais
# une DURÉE : au-delà, l'interaction Discord a expiré depuis longtemps et le
# rapport ne trouve plus personne à qui parler.
MAX_MEDIAS = 1000
LIMITE_DEFAUT = 200

# Le plafond de MESSAGES est distinct : un salon de discussion où traîne une
# image tous les cent messages épuiserait cent requêtes d'historique avant de
# trouver de quoi travailler, sans jamais atteindre le plafond de médias.
MAX_MESSAGES = 20_000

# Discord limite la fréquence d'édition d'un message. Quand tout est doublon, un
# paquet passe en une seconde : sans ce pas, la barre de progression déclencherait
# elle-même les 429 qu'elle est censée rendre visibles.
PAS_PROGRESSION = 3.0
FENETRE_DEFAUT = "7j"

# Quatre images en vol : le téléchargement et la vision sont de l'attente pure,
# la conversion WebP est du CPU sur deux cœurs. Au-delà, on ne gagne plus que
# des 429 côté OpenAI.
PAQUET = 4

Decrire = Callable[[str, str], Awaitable[str]]
# Le bilan seul disait « 2 rangés » sans jamais dire sur combien : le second
# argument est le nombre de médias TROUVÉS, c'est-à-dire le dénominateur.
Progression = Callable[[meme_import.Bilan, int], Awaitable[None]]


def fenetre(depuis: str) -> datetime | None:
    """Borne basse de l'historique à ratisser. `None` pour tout le salon.

    Accepte `7j`, `12h`, `tout`, ou une date `2026-08-01`. Refuse le reste par
    son nom plutôt que de retomber sur un défaut : ratisser tout un salon parce
    qu'on a écrit « semaine » au lieu de « 7j » se paye en descriptions.
    """
    valeur = (depuis or "").strip().lower()
    if valeur in ("tout", "all", "*"):
        return None
    if m := _DUREE.match(valeur):
        nombre, unite = int(m.group(1)), m.group(2)
        delta = timedelta(hours=nombre) if unite == "h" else timedelta(days=nombre)
        return datetime.now(timezone.utc) - delta
    try:
        return datetime.strptime(valeur, "%Y-%m-%d").replace(tzinfo=PARIS)
    except ValueError:
        raise ValueError(
            f"« {depuis} » n'est pas une fenêtre lisible, attendus : 7j, 12h, "
            f"tout, ou une date 2026-08-01"
        ) from None


async def collecter(salon, apres: datetime | None, moi: int | None = None,
                    plafond: int = MAX_MEDIAS) -> list[tuple[str, str]]:
    """Les médias admis du salon, du plus ancien au plus récent.

    L'ordre chronologique n'est pas cosmétique : les memes reçoivent leur numéro
    dans cet ordre, et un `meme12` plus vieux que `meme8` rendrait la banque
    illisible pour qui la range à la main.

    Les messages de Wally lui-même sont écartés : il annonce chaque rangement
    dans le salon, pièce jointe comprise. Les reprendre ferait repasser toute la
    banque par le téléchargement à chaque ratissage.
    """
    trouves: list[tuple[str, str]] = []
    lus = 0
    async for message in salon.history(after=apres, limit=None, oldest_first=True):
        lus += 1
        if lus > MAX_MESSAGES:
            logger.warning(
                "Ratissage arrêté après {n} messages dans {s} — restreindre la fenêtre",
                n=MAX_MESSAGES, s=getattr(salon, "id", "?"),
            )
            break
        if moi is not None and getattr(message.author, "id", None) == moi:
            continue
        for url, suffixe in images_du_message(message):
            if suffixe not in _EXTENSIONS_MEDIA:
                continue
            trouves.append((url, suffixe))
            if len(trouves) >= plafond:
                logger.warning(
                    "Ratissage borné à {n} médias dans {s} — relancer pour la suite",
                    n=plafond, s=getattr(salon, "id", "?"),
                )
                return trouves
    return trouves


@dataclass
class _Prepare:
    """Une image rapatriée, tranchée, et décrite si elle en valait la peine."""

    url: str
    prepare: meme_import.Preparation
    origine: bytes = b""
    description: str = ""


async def _rapatrier(session: meme_import.SessionImport, url: str, suffixe: str,
                     decrire: Decrire) -> _Prepare:
    """Télécharge, prépare, et ne décrit QUE ce qui sera effectivement rangé."""
    try:
        octets = await telecharger(url)
    except Exception as e:  # noqa: BLE001 — un CDN qui refuse ne coupe pas le lot
        logger.warning("Meme non rapatrié depuis {u} : {e!r}", u=url, e=e)
        return _Prepare(url, meme_import.Preparation(raison=f"image impossible à récupérer : {e}"))

    prepare = await asyncio.to_thread(session.preparer, octets, suffixe)
    if prepare.refusee:
        return _Prepare(url, prepare)
    return _Prepare(url, prepare, octets, await decrire(url, suffixe))


async def importer_salon(
    salon,
    *,
    apres: datetime | None,
    limite: int,
    dossier: Path,
    decrire: Decrire,
    moi: int | None = None,
    progression: Progression | None = None,
) -> meme_import.Bilan:
    """Range tout ce que le salon porte d'admis depuis `apres`, jusqu'à `limite`."""
    medias = await collecter(salon, apres, moi)
    logger.info(
        "Ratissage de {s} : {n} média(s) trouvé(s), limite {l}",
        s=getattr(salon, "id", "?"), n=len(medias), l=limite,
    )
    return await importer_medias(
        medias, limite=limite, dossier=dossier, decrire=decrire, progression=progression
    )


async def importer_medias(
    medias: Sequence[tuple[str, str]],
    *,
    limite: int,
    dossier: Path,
    decrire: Decrire,
    progression: Progression | None = None,
) -> meme_import.Bilan:
    """Rapatrie, décrit et range une liste de médias.

    Marche par paquets : `PAQUET` images sont rapatriées et décrites en
    parallèle, puis rangées EN SÉRIE. Le rangement doit rester séquentiel — il
    mute l'index et le compteur de la session, que les préparations lisent.

    `limite` compte les memes RANGÉS, et le paquet est taillé sur ce qu'il en
    reste : décrire une onzième image pour une limite de dix, c'est un appel
    payé pour rien.
    """
    bilan = meme_import.Bilan()
    reste = list(medias)
    total = len(reste)
    # Annoncé avant même d'ouvrir la session : indexer le dossier lit 44 Mo, et
    # rapatrier puis décrire le premier paquet prend une dizaine de secondes —
    # tout ce temps-là, l'appelant n'avait rien à afficher, pas même le nombre
    # d'images qui l'attendent.
    if progression is not None:
        await progression(bilan, total)
    session = await asyncio.to_thread(meme_import.SessionImport, dossier)
    while reste and len(bilan.ranges) < limite:
        taille = min(PAQUET, limite - len(bilan.ranges))
        paquet, reste = reste[:taille], reste[taille:]
        prepares = await asyncio.gather(
            *(_rapatrier(session, url, suffixe, decrire) for url, suffixe in paquet)
        )
        for p in prepares:
            resultat = await asyncio.to_thread(
                session.ranger, p.prepare, p.description, p.origine
            )
            bilan.ajouter(resultat, decrit=bool(p.description))
        if progression is not None:
            await progression(bilan, total)
    bilan.interrompu = bool(reste)
    return bilan


def _depot_actif(bot) -> int | None:
    """L'id du salon « boîte aux lettres », ou None si le dépôt est coupé."""
    return getattr(getattr(bot.config, "discord", None), "meme_channel_id", None)


# Discord borne l'embed : 4096 caractères de description, 1024 par champ, 6000
# au total. Deux cents memes rangés dépassent la description à eux seuls.
_MAX_DESCRIPTION = 3900


# Vingt segments : au-delà, la barre passe à la ligne sur mobile et ne veut
# plus rien dire ; en dessous, un meme sur trois ne bouge pas le trait.
_SEGMENTS = 20


def barre(fait: int, total: int, segments: int = _SEGMENTS) -> str:
    """Une barre de progression en pleins et déliés, suivie du pourcentage.

    Un total NUL arrive pour de bon — un salon qui ne porte aucune image. Une
    division par zéro sur le chemin d'affichage couperait le ratissage lui-même,
    alors qu'il n'a rien à se reprocher.
    """
    part = 0.0 if total <= 0 else max(0.0, min(1.0, fait / total))
    pleins = round(part * segments)
    return f"`{'█' * pleins}{'░' * (segments - pleins)}` {part * 100:.0f} %"


def texte_progression(bilan: meme_import.Bilan, total: int, salon) -> str:
    """Ce que l'admin lit PENDANT le ratissage.

    Le bilan seul annonçait « 2 rangés » sans dire sur combien : impossible de
    savoir s'il restait huit images ou trois cents, donc impossible de décider
    d'attendre. Le dénominateur compte les médias TRAITÉS — un doublon est du
    travail fait, même s'il n'entre pas dans la banque.
    """
    ou = getattr(salon, "mention", "?")
    if total <= 0:
        # Une barre à 0/0 et un « ✅ 0 rangé » laissent croire à un travail en
        # cours ; il n'y a simplement rien à ranger.
        return f"Aucun média à ranger dans {ou}."
    traites = len(bilan.ranges) + len(bilan.doublons) + len(bilan.refus)
    lignes = [
        f"**{total} média{'s' if total > 1 else ''} trouvé{'s' if total > 1 else ''}** dans {ou}",
        f"{barre(traites, total)}, {traites}/{total}",
    ]
    # Tant que rien n'est traité, la ligne de comptes ne dirait que des zéros.
    if traites:
        comptes = [f"✅ {len(bilan.ranges)} rangé{'s' if len(bilan.ranges) > 1 else ''}"]
        if bilan.doublons:
            comptes.append(
                f"🔁 {len(bilan.doublons)} doublon{'s' if len(bilan.doublons) > 1 else ''}"
            )
        if bilan.refus:
            comptes.append(f"⚠️ {len(bilan.refus)} écarté{'s' if len(bilan.refus) > 1 else ''}")
        lignes.append(" · ".join(comptes))
    return "\n".join(lignes)


def periode_lisible(apres: datetime | None, jusqu_a: datetime) -> str:
    """La fenêtre réellement ratissée, en heure de Paris.

    Rendre le `depuis` tel qu'il a été tapé (« 7j ») laisse le lecteur calculer
    lui-même sur quoi on vient de tirer — et l'hôte étant en UTC, il
    calculerait faux de deux heures.
    """
    fin = jusqu_a.astimezone(PARIS)
    if apres is None:
        return f"tout l'historique, jusqu'au {fin:%d/%m/%Y à %Hh%M}"
    return f"du {apres.astimezone(PARIS):%d/%m/%Y à %Hh%M} au {fin:%d/%m/%Y à %Hh%M}"


def rapport_embed(cible, bilan: meme_import.Bilan, *, apres: datetime | None,
                  fin: datetime, duree: float) -> discord.Embed:
    """Le compte rendu d'un ratissage, destiné au SALON et pas à l'admin seul.

    Public par choix : ranger trois cents memes change la banque que tout le
    monde voit défiler sur l'overlay. Un rapport éphémère disparaît avec
    l'onglet, et plus personne ne peut dire d'où sortent les nouveaux memes.

    Les refus restent NOMMÉS ici comme dans `Bilan.texte()` — un compte seul
    laisse chercher dans le dossier ce qui manque.
    """
    embed = discord.Embed(
        title="Memes rangés",
        colour=discord.Colour.green() if bilan.ranges else discord.Colour.greyple(),
    )
    embed.add_field(name="Salon ratissé", value=getattr(cible, "mention", "?"), inline=True)
    # Un ratissage de trois cents memes se compte en minutes : « 214 s » oblige
    # le lecteur à diviser.
    lisible = f"{duree:.0f} s" if duree < 90 else f"{duree / 60:.0f} min"
    embed.add_field(name="Durée", value=lisible, inline=True)
    embed.add_field(name="Période", value=periode_lisible(apres, fin), inline=False)
    embed.add_field(name="Rangés", value=str(len(bilan.ranges)), inline=True)
    embed.add_field(name="Doublons", value=str(len(bilan.doublons)), inline=True)
    # Zéro écarté est une bonne nouvelle qui n'a pas besoin d'une case ; un
    # écarté, lui, doit se voir sans qu'on aille lire les logs.
    if bilan.refus:
        embed.add_field(name="Écartés", value=str(len(bilan.refus)), inline=True)
    if bilan.muets:
        embed.add_field(name="Sans description", value=str(bilan.muets), inline=True)

    lignes: list[str] = []
    if bilan.ranges:
        lignes.append(" ".join(f"`{n}`" for n in bilan.ranges))
    lignes += [f"· {r}" for r in bilan.refus[:3]]
    if len(bilan.refus) > 3:
        lignes.append(f"· … et {len(bilan.refus) - 3} autre(s)")
    if bilan.interrompu:
        lignes.append("_Limite atteinte : relance la commande pour la suite._")
    if lignes:
        embed.description = "\n".join(lignes)[:_MAX_DESCRIPTION]
    return embed


class MemeMasseCog(commands.Cog):
    """Les deux chemins d'import sans aperçu : le rattrapage et le fil de l'eau."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self._depot_annonce = False

    async def _decrire(self, url: str, suffixe: str) -> str:
        return await decrire_image(self.bot, url, suffixe)

    # ── Ratisser un salon ─────────────────────────────────────────────────────

    @app_commands.command(
        name="importer-memes",
        description="Range en masse les memes d'un salon (admin)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        salon="Le salon à ratisser (par défaut : celui-ci)",
        depuis="Fenêtre : 7j, 12h, tout, ou une date 2026-08-01",
        limite=f"Nombre maximum de memes rangés (défaut {LIMITE_DEFAUT})",
    )
    async def importer(
        self,
        interaction: discord.Interaction,
        salon: discord.TextChannel | None = None,
        depuis: str = FENETRE_DEFAUT,
        limite: int = LIMITE_DEFAUT,
    ) -> None:
        # Avant le defer : une fenêtre mal écrite doit se dire tout de suite,
        # pas après trois minutes de ratissage.
        try:
            apres = fenetre(depuis)
        except ValueError as e:
            await interaction.response.send_message(content=str(e), ephemeral=True)
            return
        if not 1 <= limite <= MAX_MEDIAS:
            await interaction.response.send_message(
                content=f"La limite doit tenir entre 1 et {MAX_MEDIAS}.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        cible = salon or interaction.channel
        # En message privé, `interaction.channel` est un DMChannel sans serveur
        # ni permissions : il n'y a personne à qui demander l'historique.
        if interaction.guild is None or not isinstance(cible, (discord.TextChannel,
                                                              discord.Thread)):
            await interaction.followup.send(
                content="Cette commande ratisse un salon de serveur, pas un message privé.",
                ephemeral=True,
            )
            return
        droits = cible.permissions_for(interaction.guild.me)
        if not droits.read_message_history:
            await interaction.followup.send(
                content=f"Je n'ai pas « Voir l'historique des messages » dans {cible.mention}.",
                ephemeral=True,
            )
            return

        depart = datetime.now(timezone.utc)
        muet = False  # passe à vrai dès que l'interaction n'écoute plus
        derniere = depart
        premiere = True

        async def _avancer(bilan: meme_import.Bilan, total: int) -> None:
            # Le tout premier passage échappe au pas : c'est lui qui annonce
            # combien de médias ont été trouvés, et le retenir trois secondes
            # laisserait l'admin devant un « Wally réfléchit… » muet pendant
            # que le premier paquet se télécharge.
            nonlocal muet, derniere, premiere
            maintenant = datetime.now(timezone.utc)
            trop_tot = (maintenant - derniere).total_seconds() < PAS_PROGRESSION
            if muet or (trop_tot and not premiere):
                return
            premiere = False
            derniere = maintenant
            try:
                await interaction.edit_original_response(
                    content=texte_progression(bilan, total, cible)
                )
            except Exception as e:  # noqa: BLE001 — le token d'interaction dure 15 min
                muet = True
                logger.info("Progression du ratissage plus éditable : {e!r}", e=e)

        try:
            bilan = await importer_salon(
                cible, apres=apres, limite=limite, dossier=DOSSIER_MEMES,
                decrire=self._decrire, moi=self.bot.user.id, progression=_avancer,
            )
        except Exception as e:  # noqa: BLE001 — un salon fermé ne casse pas le bot
            logger.error("Ratissage de memes échoué : {e!r}", e=e)
            await interaction.followup.send(
                content=f"Ratissage interrompu : {e}", ephemeral=True
            )
            return

        fin = datetime.now(timezone.utc)
        duree = (fin - depart).total_seconds()
        logger.info(
            "Ratissage de {s} terminé en {d:.0f} s : {n} rangé(s), {dbl} doublon(s), "
            "{r} refus", s=cible.id, d=duree, n=len(bilan.ranges),
            dbl=len(bilan.doublons), r=len(bilan.refus),
        )
        # La barre de progression est éphémère et resterait figée sur
        # « Rangement en cours… » : elle doit se clore, le rapport est ailleurs.
        if not muet:
            try:
                await interaction.edit_original_response(content="Ratissage terminé.")
            except Exception as e:  # noqa: BLE001 — l'interaction a pu expirer
                logger.info("Fin de progression non éditable : {e!r}", e=e)

        # Envoyé par le SALON et non par `followup.send(ephemeral=False)` : le
        # premier followup d'une interaction déférée en éphémère hérite de ce
        # flag, et le rapport « public » serait resté invisible pour tout le
        # monde sauf l'admin, sans la moindre erreur pour le dire.
        embed = rapport_embed(cible, bilan, apres=apres, fin=fin, duree=duree)
        # Là où la commande a été tapée, sauf si ce n'est pas un salon qui sait
        # écrire (racine de forum, catégorie) — auquel cas le salon ratissé, qui
        # a déjà passé la garde plus haut, fait un destinataire valable.
        ou = interaction.channel
        if not isinstance(ou, (discord.TextChannel, discord.Thread)):
            ou = cible
        try:
            await ou.send(embed=embed)
        except Exception as e:  # noqa: BLE001 — salon fermé en écriture, ou supprimé
            logger.warning("Rapport de ratissage non remis au salon, envoi en DM : {e!r}", e=e)
            rapport = f"Ratissage de {cible.mention} ({depuis}), {bilan.texte()}"
            await _en_message_prive(interaction.user, rapport[:_MAX_CONTENU])

    # ── Boîte aux lettres ─────────────────────────────────────────────────────

    @commands.Cog.listener("on_ready")
    async def annoncer_le_depot(self) -> None:
        """Dit une fois si la boîte aux lettres est armée, et sur quel salon.

        `on_ready` retombe à chaque reconnexion : sans le drapeau, la ligne
        reviendrait à chaque coupure réseau et ne voudrait plus rien dire.
        """
        if self._depot_annonce:
            return
        self._depot_annonce = True
        salon_id = _depot_actif(self.bot)
        if salon_id is None:
            logger.info("Dépôt automatique de memes : coupé (aucun salon configuré)")
            return
        salon = self.bot.get_channel(salon_id)
        if salon is None:
            logger.warning(
                "Dépôt automatique de memes : salon {s} INTROUVABLE — rien n'y sera rangé",
                s=salon_id,
            )
            return
        logger.info("Dépôt automatique de memes armé sur #{s}", s=salon.name)

    @commands.Cog.listener("on_message")
    async def au_fil_de_l_eau(self, message) -> None:
        """Range ce qui tombe dans le salon de dépôt, sans commande ni aperçu.

        Wally s'écarte lui-même : il annonce ses propres rangements dans le
        salon, pièce jointe comprise — sans cette garde, chaque meme rangé en
        déclencherait un autre.
        """
        salon_depot = _depot_actif(self.bot)
        if salon_depot is None or getattr(message.channel, "id", None) != salon_depot:
            return
        if getattr(message.author, "id", None) == self.bot.user.id:
            return
        medias = [(u, s) for u, s in images_du_message(message) if s in _EXTENSIONS_MEDIA]
        if not medias:
            return

        try:
            bilan = await importer_medias(
                medias, limite=len(medias), dossier=DOSSIER_MEMES, decrire=self._decrire
            )
        except Exception as e:  # noqa: BLE001 — un disque plein ne casse pas le salon
            logger.error("Dépôt automatique de meme échoué : {e!r}", e=e)
            await _reagir(message, "⚠️")
            return

        if bilan.ranges:
            logger.info(
                "Memes déposés dans le salon de dépôt : {n}", n=", ".join(bilan.ranges)
            )
            await _reagir(message, "✅")
        elif bilan.doublons:
            await _reagir(message, "🔁")
        else:
            await _reagir(message, "⚠️")
        if bilan.refus:
            # La réaction seule ne dit pas POURQUOI, et personne ne va lire les
            # logs du bot pour un meme qui n'est pas entré.
            try:
                await message.reply(bilan.texte(), mention_author=False)
            except Exception as e:  # noqa: BLE001 — le message a pu être supprimé
                logger.warning("Motif d'écart non remis dans le salon : {e!r}", e=e)


async def _reagir(message, emoji: str) -> None:
    """Le seul retour visible du dépôt automatique — il ne doit jamais lever."""
    try:
        await message.add_reaction(emoji)
    except Exception as e:  # noqa: BLE001 — permission de réaction absente, message supprimé
        logger.warning("Réaction {e_} impossible sur un dépôt de meme : {e!r}", e_=emoji, e=e)


async def _en_message_prive(utilisateur, texte: str) -> None:
    try:
        await utilisateur.send(texte)
    except Exception as e:  # noqa: BLE001 — DM fermés : le rapport reste dans les logs
        logger.warning("Rapport de ratissage non remis en DM : {e!r}", e=e)
