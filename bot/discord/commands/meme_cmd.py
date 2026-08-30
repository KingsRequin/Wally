# bot/discord/commands/meme_cmd.py
"""« Ranger ce meme » — clic droit sur un message, menu Applications.

Discord impose qu'un formulaire soit la PREMIÈRE réponse à une interaction, sous
trois secondes, et interdit de faire patienter avant. Décrire une image en prend
cinq à dix : un formulaire déjà rempli par la description est donc impossible.
D'où le passage par un aperçu à boutons, où « Corriger » ouvre le formulaire —
un clic de plus, mais la description est relue avant d'être écrite.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.core import meme_import
from bot.core.memes import MAX_DESCRIPTION, _EXTENSIONS, _EXTENSIONS_MEDIA, tronquer_description
from bot.core.scrape import ScrapeService

DOSSIER_MEMES = Path("data/memes")

# Le cyan d'accent du projet, celui du dashboard et de l'écran de chargement
# d'`/wally imagine`.
COULEUR_ACCENT = "#06b6d4"

# Ce qu'une annonce de lot peut porter en pièces jointes. Discord refuse le
# message ENTIER au-delà : sans borne, dix memes bien rangés passeraient pour
# perdus parce que leur annonce n'est jamais partie.
_MAX_ANNONCE = 8 * 1024 * 1024
_MAX_FICHIERS_ANNONCE = 10

# Un message Discord est refusé au-delà de 2 000 caractères : dix descriptions
# de 160 y tiennent, mais leurs motifs d'écart peuvent déborder.
_MAX_CONTENU = 1900

# Ce que l'aperçu laisse le temps de décider avant de se figer.
DELAI_APERCU = 120.0

# Un CDN qui ne répond pas ne doit pas immobiliser l'interaction jusqu'à son
# expiration : le refus explicite vaut mieux que l'attente muette.
DELAI_TELECHARGEMENT = aiohttp.ClientTimeout(total=30)

# aiohttp suit les redirections par défaut, ce qui contournerait la garde SSRF :
# on les suit à la main, en revalidant chaque saut.
MAX_REDIRECTIONS = 3
_REDIRECTIONS = frozenset({301, 302, 303, 307, 308})


def images_du_message(message) -> list[tuple[str, str]]:
    """`(url, suffixe)` de TOUS les médias du message, sans doublon d'URL.

    Les pièces jointes d'abord, les embeds ensuite — ce qui rattrape les liens
    Tenor ou Klipy postés sans fichier. Un embed annonce souvent la même image
    en `image` et en `thumbnail` : la retenir deux fois ferait deux
    téléchargements pour un seul meme.

    Le format n'est PAS filtré ici. Filtrer au plus tôt semblait propre, mais
    rendait « ce message ne porte aucune image » devant un `.mov` d'iPhone ou un
    `.heic` — le mensonge déplacé de l'aperçu vers l'entrée. C'est à l'appelant
    de nommer le format trouvé et la liste des formats admis.
    """
    trouves: list[tuple[str, str]] = []
    vues: set[str] = set()

    def _retenir(url: str, suffixe: str) -> None:
        if suffixe and url not in vues:
            vues.add(url)
            trouves.append((url, suffixe))

    for a in message.attachments:
        if a.content_type and a.content_type.startswith(("image/", "video/")):
            _retenir(a.url, Path(urlparse(a.url).path).suffix.lower())
    for embed in message.embeds:
        for source in (getattr(embed, "image", None), getattr(embed, "thumbnail", None)):
            url = getattr(source, "url", None)
            if url:
                _retenir(url, Path(urlparse(url).path).suffix.lower())
    return trouves


def image_du_message(message) -> tuple[str, str] | None:
    """Le premier média ADMIS du message, à défaut le premier trouvé.

    Les formats admis restent PRIORITAIRES : un message portant un `.heic` et un
    `.png` range le `.png`, sans rien demander à personne. Le repli sur un
    format non admis n'est pas une erreur — il permet de le NOMMER.
    """
    trouves = images_du_message(message)
    admis = [t for t in trouves if t[1] in _EXTENSIONS_MEDIA]
    if admis:
        return admis[0]
    return trouves[0] if trouves else None


async def cible_publique(url: str) -> str:
    """Raison du refus, ou chaîne vide si l'URL peut être rapatriée.

    L'URL vient d'un embed, donc de l'extérieur : un webhook qui poste
    `http://192.168.1.185:5001/x.png` ou `http://wally-qdrant:6333/…` ferait
    rapatrier la réponse depuis le réseau du conteneur, l'écrirait sur disque et
    la republierait en pièce jointe dans le salon. La résolution est celle du
    scrape — `_adresses_publiques`, partagée : deux tamis SSRF finiraient par
    diverger. `is_scrapable_url` en entier ne convient PAS ici : il refuse
    justement les URL d'image, qui sont tout ce qu'on vient chercher.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"schéma « {parsed.scheme or '?'} » refusé, seuls http et https passent"
    hote = (parsed.hostname or "").lower().rstrip(".")
    if not hote:
        return "URL sans hôte"
    # Un nom sans point est un alias de service Docker (`wally-qdrant`,
    # `firecrawl-api`). La résolution seule ne suffit pas à les écarter : un
    # résolveur qui détourne les NXDOMAIN rend une IP publique pour n'importe
    # quel nom. Même règle que `is_scrapable_url`, pour la même raison.
    if "." not in hote and not _est_ip(hote):
        return f"{hote} est un nom interne (sans domaine)"
    if not await asyncio.to_thread(ScrapeService._adresses_publiques, hote):
        return f"{hote} n'est pas une adresse publique"
    return ""


def _est_ip(hote: str) -> bool:
    try:
        ipaddress.ip_address(hote)
    except ValueError:
        return False
    return True


async def telecharger(url: str, limite: int = meme_import.MAX_TELECHARGEMENT) -> bytes:
    """Rapatrie l'image. Coupe net au-delà de la limite plutôt que de tout avaler.

    Chaque saut de redirection repasse par la garde : une cible publique qui
    renvoie un `Location:` interne suffirait sinon à la contourner.
    """
    async with aiohttp.ClientSession(timeout=DELAI_TELECHARGEMENT) as session:
        for _ in range(MAX_REDIRECTIONS + 1):
            refus = await cible_publique(url)
            if refus:
                raise PermissionError(refus)
            async with session.get(url, allow_redirects=False) as reponse:
                if reponse.status in _REDIRECTIONS:
                    suivant = reponse.headers.get("Location")
                    if not suivant:
                        raise ValueError(f"redirection {reponse.status} sans destination")
                    url = urljoin(url, suivant)
                    continue
                reponse.raise_for_status()
                morceaux: list[bytes] = []
                total = 0
                async for bloc in reponse.content.iter_chunked(64 * 1024):
                    total += len(bloc)
                    if total > limite:
                        raise ValueError(f"fichier au-delà de {limite / 1e6:.0f} Mo")
                    morceaux.append(bloc)
                return b"".join(morceaux)
    raise ValueError(f"plus de {MAX_REDIRECTIONS} redirections")


@dataclass
class Entree:
    """Une image prête à ranger, telle qu'elle sera ÉCRITE.

    `octets` sont ceux d'après conversion : la préparation a déjà tranché le
    format, le doublon et le poids, et repasser l'original au rangement le
    reconvertirait pour rien. D'où `converti`, que le résultat du rangement ne
    peut plus dire — il ne voit qu'un `.webp` qu'il n'a pas produit.
    """

    octets: bytes
    suffixe: str
    description: str = ""
    converti: bool = False


def _embed_annonce(resultat: meme_import.ResultatImport, auteur) -> discord.Embed:
    """L'annonce publique d'un meme rangé.

    Ne porte PAS la description : elle est le contexte que Wally lit pour
    commenter une image qu'il ne voit pas, pas un texte à afficher. Même règle
    que sur l'overlay, où la légende a été retirée pour cette raison.

    `set_image` n'est posé que sur un format affichable : Discord ne joue pas de
    vidéo dans un embed, et l'y désigner rend un cadre qui ne se remplit jamais
    — le meme paraîtrait manquant alors qu'il est joint juste en dessous.
    """
    embed = discord.Embed(
        title="Nouveau meme dans la banque",
        colour=discord.Colour.from_str(COULEUR_ACCENT),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Fichier", value=f"`{resultat.nom}`", inline=True)
    poids = f"{resultat.octets / 1024:.0f} Ko"
    embed.add_field(
        name="Poids", value=f"{poids} (WebP)" if resultat.converti else poids, inline=True
    )
    if Path(resultat.nom).suffix.lower() in _EXTENSIONS:
        embed.set_image(url=f"attachment://{resultat.nom}")
    embed.set_footer(
        text=f"Rangé par {auteur.display_name}",
        icon_url=getattr(getattr(auteur, "display_avatar", None), "url", None),
    )
    return embed


class FormulaireDescription(discord.ui.Modal, title="Description du meme"):
    """Le texte qui servira de vision à Wally — jamais affiché aux spectateurs.

    Ne s'ouvre que sur un aperçu à une seule image : un champ unique ne peut pas
    corriger dix descriptions, et la vue retire le bouton au-delà.
    """

    def __init__(self, vue: "VueRangement") -> None:
        super().__init__()
        self._vue = vue
        # `default` DOIT tenir dans `max_length` : discord.py ne le vérifie pas,
        # c'est l'API qui rejette en 400 et `send_modal` lève — le bouton
        # « Corriger » cassait sur toute description un peu longue, alors que la
        # vision tourne à 400 tokens, soit quatre fois cette borne.
        self.description: discord.ui.TextInput = discord.ui.TextInput(
            label="Ce que Wally doit savoir de l'image",
            style=discord.TextStyle.paragraph,
            default=tronquer_description(vue.entrees[0].description),
            required=False,
            max_length=MAX_DESCRIPTION,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._vue.entrees[0].description = tronquer_description(str(self.description.value))
        await self._vue.ranger(interaction)


def _recapitulatif(resultats: list[meme_import.ResultatImport]) -> str:
    """Le compte rendu d'un lot : ce qui est rangé, ce qui ne l'est pas et pourquoi.

    Les refus sont NOMMÉS. Un « 7 rangés » sur dix images laisse chercher les
    trois manquantes dans le dossier ; « 2 doublons, 1 refusé : 9,4 Mo après
    conversion » les explique sur place.
    """
    ranges = [r for r in resultats if r.ok]
    doublons = [r for r in resultats if r.doublon]
    refuses = [r for r in resultats if not r.ok and not r.doublon]

    def _n(quoi: str, combien: int) -> str:
        return f"{combien} {quoi}{'s' if combien > 1 else ''}"

    bouts = [f"**{_n('rangé', len(ranges))}**"]
    if doublons:
        bouts.append(_n("doublon", len(doublons)))
    if refuses:
        bouts.append(_n("refusé", len(refuses)))
    lignes = [", ".join(bouts) + "."]
    if ranges:
        lignes.append(" ".join(f"`{r.nom}`" for r in ranges))
    lignes += [f"· {r.raison}" for r in refuses[:3]]
    return "\n".join(lignes)


def _embed_annonce_lot(resultats: list[meme_import.ResultatImport], auteur) -> discord.Embed:
    """Une SEULE annonce pour tout le lot.

    Un embed par meme, c'est dix messages à la suite dans le salon : le lot
    passerait pour une avalanche du bot.
    """
    embed = discord.Embed(
        title=f"{len(resultats)} nouveaux memes dans la banque",
        colour=discord.Colour.from_str(COULEUR_ACCENT),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Fichiers",
        value=" ".join(f"`{r.nom}`" for r in resultats)[:1024],
        inline=False,
    )
    embed.add_field(
        name="Poids", value=f"{sum(r.octets for r in resultats) / 1024:.0f} Ko", inline=True
    )
    embed.set_footer(
        text=f"Rangés par {auteur.display_name}",
        icon_url=getattr(getattr(auteur, "display_avatar", None), "url", None),
    )
    return embed


class VueRangement(discord.ui.View):
    """Aperçu avant écriture : ranger tel quel, corriger, ou renoncer.

    Porte une LISTE : un message Discord transporte jusqu'à dix fichiers, et
    n'en ranger qu'un jetait les neuf autres.
    """

    def __init__(self, auteur_id: int, entrees: list[Entree], salon) -> None:
        super().__init__(timeout=DELAI_APERCU)
        self.auteur_id = auteur_id
        self.entrees = entrees
        self.salon = salon
        # Renseigné par l'appelant : sans lui, `on_timeout` n'a rien à éteindre.
        self.message: discord.Message | None = None
        if len(entrees) > 1:
            # Un champ unique ne peut pas corriger dix descriptions : le bouton
            # ne pourrait que mentir sur celle qu'il modifie.
            self.remove_item(self.bouton_corriger)
            self.bouton_ranger.label = f"Ranger les {len(entrees)}"

    async def on_timeout(self) -> None:
        """Éteint les boutons plutôt que de les laisser mentir.

        Passé le délai, Discord ne route plus l'interaction : cliquer rendait
        « Cette interaction a échoué », ce qui ressemble à une panne du bot.
        """
        for enfant in self.children:
            if isinstance(enfant, discord.ui.Button):
                enfant.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(view=self)
        except Exception as e:  # noqa: BLE001 — l'aperçu a pu être supprimé entre-temps
            logger.debug("Aperçu de meme non grisé à l'expiration : {e!r}", e=e)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.auteur_id:
            await interaction.response.send_message(
                "Ce rangement n'est pas le tien.", ephemeral=True
            )
            return False
        return True

    def _ranger_tout(self) -> list[meme_import.ResultatImport]:
        """Le lot entier sur UNE session : un index lu une fois, des numéros qui
        s'enchaînent, et la dédup qui vaut aussi entre les images du lot.

        Le dossier est relu ici et non à l'aperçu : deux minutes ont pu passer,
        et le même meme a pu être rangé entre-temps par quelqu'un d'autre.
        """
        session = meme_import.SessionImport(DOSSIER_MEMES)
        return [session.importer(e.octets, e.suffixe, e.description) for e in self.entrees]

    async def ranger(self, interaction: discord.Interaction) -> None:
        try:
            resultats = await asyncio.to_thread(self._ranger_tout)
        except Exception as e:  # noqa: BLE001 — un disque plein ne casse pas le bot
            logger.error("Import de meme échoué : {e!r}", e=e)
            await interaction.response.edit_message(
                content=f"Erreur inattendue, rien n'a été rangé : {e}", view=None
            )
            return

        ranges = [r for r in resultats if r.ok]
        if len(resultats) == 1:
            resultat = resultats[0]
            if not resultat.ok:
                message = (f"Déjà rangé sous **{resultat.doublon}**." if resultat.doublon
                           else f"Pas rangé : {resultat.raison}")
                await interaction.response.edit_message(content=message, view=None)
                return
            poids = f"{resultat.octets / 1024:.0f} Ko"
            converti = " (converti en WebP)" if resultat.converti or self.entrees[0].converti\
                else ""
            message = f"Rangé sous **{resultat.nom}**{converti}, {poids}."
        else:
            message = _recapitulatif(resultats)

        await interaction.response.edit_message(content=message, view=None)
        for r in ranges:
            logger.info("Meme rangé : {n} par {u}", n=r.nom, u=interaction.user.display_name)
        if ranges:
            await self._annoncer(interaction, ranges)
        self.stop()

    async def _annoncer(self, interaction: discord.Interaction,
                        ranges: list[meme_import.ResultatImport]) -> None:
        """Publie le ou les memes dans le salon d'origine.

        Le seul appel réseau du chemin d'écriture qui échoue ORDINAIREMENT :
        permission « Joindre des fichiers » absente, salon en lecture seule, ou
        fichier au-dessus de la limite d'upload du serveur (10 Mo, quand le
        téléchargement en autorise 16). Sans garde, l'exception partait dans
        `View.on_error` — donc dans le `logging` standard, hors des sinks du
        projet — et l'utilisateur restait sur un « Rangé » sans annonce.
        """
        try:
            if len(ranges) == 1:
                # `discord.File` OUVRE le fichier : bloquant, comme tout le reste ici.
                fichier = await asyncio.to_thread(discord.File, DOSSIER_MEMES / ranges[0].nom)
                await self.salon.send(
                    embed=_embed_annonce(ranges[0], interaction.user), file=fichier
                )
                return
            joints = _joignables(ranges)
            fichiers = await asyncio.to_thread(
                lambda: [discord.File(DOSSIER_MEMES / r.nom) for r in joints]
            )
            await self.salon.send(
                embed=_embed_annonce_lot(ranges, interaction.user), files=fichiers
            )
        except Exception as e:  # noqa: BLE001 — le fichier EST rangé, seule l'annonce manque
            noms = ", ".join(r.nom for r in ranges)
            logger.error("Annonce publique du meme {n} impossible : {e!r}", n=noms, e=e)
            await interaction.followup.send(
                content=(f"**{noms}** est bien rangé, mais l'annonce dans le "
                         f"salon n'a pas pu partir : {e}"),
                ephemeral=True,
            )

    @discord.ui.button(label="Ranger", style=discord.ButtonStyle.success)
    async def bouton_ranger(self, interaction: discord.Interaction, _b) -> None:
        await self.ranger(interaction)

    @discord.ui.button(label="Corriger", style=discord.ButtonStyle.secondary)
    async def bouton_corriger(self, interaction: discord.Interaction, _b) -> None:
        await interaction.response.send_modal(FormulaireDescription(self))

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger)
    async def bouton_annuler(self, interaction: discord.Interaction, _b) -> None:
        await interaction.response.edit_message(content="Abandonné.", view=None)
        self.stop()


def _joignables(ranges: list[meme_import.ResultatImport]) -> list[meme_import.ResultatImport]:
    """Ce qu'une seule annonce peut porter : dix fichiers, huit mégaoctets.

    Un meme trop lourd est SAUTÉ, pas terminal : s'arrêter au premier priverait
    d'illustration ceux qui le suivent. L'embed, lui, les nomme tous — c'est le
    rangement qu'il annonce, pas la pièce jointe.
    """
    retenus: list[meme_import.ResultatImport] = []
    total = 0
    for r in ranges:
        if len(retenus) >= _MAX_FICHIERS_ANNONCE:
            break
        if total + r.octets > _MAX_ANNONCE:
            continue
        retenus.append(r)
        total += r.octets
    return retenus


class MemeCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.menu = app_commands.ContextMenu(name="Ranger ce meme", callback=self.ranger)
        # Le dossier alimente un overlay diffusé en direct : un dépôt malvenu
        # sortirait à l'antenne.
        self.menu.default_permissions = discord.Permissions(manage_guild=True)
        bot.tree.add_command(self.menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    async def ranger(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(ephemeral=True)
        trouves = images_du_message(message)
        if not trouves:
            await interaction.followup.send(
                content="Ce message ne porte aucune image.", ephemeral=True
            )
            return
        admis = [(u, s) for u, s in trouves if s in _EXTENSIONS_MEDIA]
        # Des images bien présentes, mais dans un format qu'on ne range pas. Le
        # dire ici, avant tout téléchargement : « aucune image » devant un .mov
        # d'iPhone envoie chercher un problème dans le message, pas le format.
        if not admis:
            formats = " ".join(sorted({s for _, s in trouves}))
            attendus = " ".join(sorted(_EXTENSIONS_MEDIA))
            await interaction.followup.send(
                content=f"Format `{formats}` non admis, attendus : {attendus}.",
                ephemeral=True,
            )
            return

        try:
            entrees, doublons, refus = await self._preparer(admis)
        except Exception as e:  # noqa: BLE001 — un dossier illisible ne casse pas le bot
            logger.error("Aperçu de meme échoué : {e!r}", e=e)
            await interaction.followup.send(
                content=f"Erreur inattendue, rien n'a été rangé : {e}", ephemeral=True
            )
            return

        if not entrees:
            await interaction.followup.send(
                content=_rien_a_ranger(doublons, refus), ephemeral=True
            )
            return

        ecartes = len(trouves) - len(admis)
        vue = VueRangement(interaction.user.id, entrees, message.channel)
        vue.message = await interaction.followup.send(
            content=_apercu(entrees, doublons, refus, ecartes),
            view=vue,
            ephemeral=True,
            wait=True,
        )

    async def _preparer(
        self, medias: list[tuple[str, str]]
    ) -> tuple[list[Entree], list[str], list[str]]:
        """Rapatrie, dédoublonne, puis décrit — dans cet ordre.

        L'ordre est ce qui compte : décrire coûte un appel facturé et deux à
        cinq secondes par image. Le faire avant de savoir si le meme est déjà
        rangé, c'est payer pour un fichier qu'on jette — et sur un message de
        dix images repostées, payer dix fois.

        La session est partagée par tout le message : sans elle, chaque
        préparation relirait les 44 Mo du dossier, et deux images identiques du
        même message passeraient toutes les deux.
        """
        session = await asyncio.to_thread(meme_import.SessionImport, DOSSIER_MEMES)
        entrees: list[Entree] = []
        doublons: list[str] = []
        refus: list[str] = []
        vues: set[str] = set()
        for url, suffixe in medias:
            try:
                octets = await telecharger(url)
            except Exception as e:  # noqa: BLE001 — un CDN qui refuse ne casse rien
                logger.warning("Meme non rapatrié depuis {u} : {e!r}", u=url, e=e)
                refus.append(f"image impossible à récupérer : {e}")
                continue
            prepare = await asyncio.to_thread(session.preparer, octets, suffixe)
            if prepare.doublon:
                doublons.append(prepare.doublon)
                continue
            if prepare.refusee:
                refus.append(prepare.raison)
                continue
            # Deux fois la même image dans un message : c'est fréquent quand un
            # embed double une pièce jointe. La seconde serait de toute façon
            # refusée au rangement, mais elle aurait été décrite d'ici là.
            empreinte = hashlib.sha256(prepare.octets).hexdigest()
            if empreinte in vues:
                refus.append("la même image apparaît deux fois dans ce message")
                continue
            vues.add(empreinte)
            entrees.append(Entree(
                prepare.octets, prepare.suffixe,
                await self._decrire(url, suffixe), prepare.converti,
            ))
        return entrees, doublons, refus

    async def _decrire(self, url: str, suffixe: str) -> str:
        return await decrire_image(self.bot, url, suffixe)


async def decrire_image(bot, url: str, suffixe: str) -> str:
    """Ce que Wally saura de l'image. Vide si la vision ne peut rien en dire.

    Point d'appel UNIQUE de la vision pour les memes, partagé par les trois
    chemins d'import : deux prompts d'analyse qui divergent, ce sont deux
    banques dont Wally ne parle pas de la même façon.
    """
    if suffixe not in _EXTENSIONS:
        return ""
    vision = getattr(bot, "vision", None)
    if vision is None or not vision.available:
        return ""
    return tronquer_description(await vision.analyze(
        [url], purpose="meme_describe", prompt_name="meme_describe_system"
    ) or "")


def _ligne_description(entree: Entree) -> str:
    """La description proposée, ou la raison de son absence.

    Deux absences, deux causes : dire « pas d'analyse pour une vidéo » devant un
    PNG que la vision n'a pas su décrire envoie chercher un problème qui
    n'existe pas.
    """
    if entree.description:
        return entree.description
    if entree.suffixe in _EXTENSIONS:
        return "_(à écrire, l'analyse de l'image n'a rien rendu)_"
    return f"_(à écrire, pas d'analyse possible sur un fichier {entree.suffixe})_"


def _apercu(entrees: list[Entree], doublons: list[str], refus: list[str],
            ecartes: int) -> str:
    """Ce que l'aperçu montre avant d'écrire quoi que ce soit."""
    if len(entrees) == 1:
        lignes = [f"**Description proposée :**\n{_ligne_description(entrees[0])}"]
    else:
        lignes = [f"**{len(entrees)} images prêtes à ranger :**"]
        lignes += [f"{i}. {_ligne_description(e)}" for i, e in enumerate(entrees, 1)]
    if doublons:
        lignes.append(f"_Déjà rangé : {', '.join(f'`{n}`' for n in doublons)}._")
    lignes += [f"_Écarté : {r}._" for r in refus[:3]]
    if ecartes:
        lignes.append(f"_{ecartes} fichier(s) au format non admis, non repris._")
    return "\n".join(lignes)[:_MAX_CONTENU]


def _rien_a_ranger(doublons: list[str], refus: list[str]) -> str:
    """Quand tout a été écarté : dire lequel des deux motifs, et lequel exactement."""
    if doublons and not refus:
        if len(doublons) == 1:
            return f"Déjà rangé sous **{doublons[0]}**."
        return f"Déjà rangé : {', '.join(f'**{n}**' for n in doublons)}."
    if refus and not doublons:
        if len(refus) == 1:
            return f"Pas rangé : {refus[0]}"
        return "Rien n'a été rangé :\n" + "\n".join(f"· {r}" for r in refus[:5])
    return (f"Rien à ranger : {len(doublons)} déjà en banque, "
            f"{len(refus)} écarté(s).\n" + "\n".join(f"· {r}" for r in refus[:3]))
