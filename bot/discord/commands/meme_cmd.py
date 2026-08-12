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

# Ce que l'aperçu laisse le temps de décider avant de se figer.
DELAI_APERCU = 120.0

# Un CDN qui ne répond pas ne doit pas immobiliser l'interaction jusqu'à son
# expiration : le refus explicite vaut mieux que l'attente muette.
DELAI_TELECHARGEMENT = aiohttp.ClientTimeout(total=30)

# aiohttp suit les redirections par défaut, ce qui contournerait la garde SSRF :
# on les suit à la main, en revalidant chaque saut.
MAX_REDIRECTIONS = 3
_REDIRECTIONS = frozenset({301, 302, 303, 307, 308})


def image_du_message(message) -> tuple[str, str] | None:
    """`(url, suffixe)` de la première image du message, ou None.

    Les pièces jointes d'abord ; à défaut l'image d'un embed, ce qui rattrape
    les liens Tenor ou Klipy postés sans fichier.

    Les deux branches appliquent le MÊME filtre d'extension. Sans lui côté pièce
    jointe, un `.bmp` était retenu, téléchargé, décrit comme une vidéo dans
    l'aperçu, puis refusé à l'écriture : trois messages faux pour un fichier que
    l'on savait écarter dès la première ligne.
    """
    for a in message.attachments:
        if a.content_type and a.content_type.startswith(("image/", "video/")):
            suffixe = Path(urlparse(a.url).path).suffix.lower()
            if suffixe in _EXTENSIONS_MEDIA:
                return a.url, suffixe
    for embed in message.embeds:
        for source in (getattr(embed, "image", None), getattr(embed, "thumbnail", None)):
            url = getattr(source, "url", None)
            if not url:
                continue
            suffixe = Path(urlparse(url).path).suffix.lower()
            if suffixe in _EXTENSIONS_MEDIA:
                return url, suffixe
    return None


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


class FormulaireDescription(discord.ui.Modal, title="Description du meme"):
    """Le texte qui servira de vision à Wally — jamais affiché aux spectateurs."""

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
            default=tronquer_description(vue.description),
            required=False,
            max_length=MAX_DESCRIPTION,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._vue.description = tronquer_description(str(self.description.value))
        await self._vue.ranger(interaction)


class VueRangement(discord.ui.View):
    """Aperçu avant écriture : ranger tel quel, corriger, ou renoncer."""

    def __init__(self, auteur_id: int, octets: bytes, suffixe: str, description: str,
                 salon) -> None:
        super().__init__(timeout=DELAI_APERCU)
        self.auteur_id = auteur_id
        self.octets = octets
        self.suffixe = suffixe
        self.description = description
        self.salon = salon
        # Renseigné par l'appelant : sans lui, `on_timeout` n'a rien à éteindre.
        self.message: discord.Message | None = None

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
            logger.debug("Aperçu de meme non grisé à l'expiration : {e}", e=e)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.auteur_id:
            await interaction.response.send_message(
                "Ce rangement n'est pas le tien.", ephemeral=True
            )
            return False
        return True

    async def ranger(self, interaction: discord.Interaction) -> None:
        try:
            resultat = await asyncio.to_thread(
                meme_import.importer, self.octets, self.suffixe, self.description, DOSSIER_MEMES
            )
        except Exception as e:  # noqa: BLE001 — un disque plein ne casse pas le bot
            logger.error("Import de meme échoué : {e}", e=e)
            await interaction.response.edit_message(
                content=f"Erreur inattendue, rien n'a été rangé : {e}", view=None
            )
            return

        if not resultat.ok:
            message = (f"Déjà rangé sous **{resultat.doublon}**." if resultat.doublon
                       else f"Pas rangé : {resultat.raison}")
            await interaction.response.edit_message(content=message, view=None)
            return

        poids = f"{resultat.octets / 1024:.0f} Ko"
        converti = " (converti en WebP)" if resultat.converti else ""
        await interaction.response.edit_message(
            content=f"Rangé sous **{resultat.nom}**{converti}, {poids}.", view=None
        )
        logger.info("Meme rangé : {n} par {u}", n=resultat.nom, u=interaction.user.display_name)
        # Le seul appel réseau du chemin d'écriture qui échoue ORDINAIREMENT :
        # permission « Joindre des fichiers » absente, salon en lecture seule, ou
        # fichier au-dessus de la limite d'upload du serveur (10 Mo, quand le
        # téléchargement en autorise 16). Sans garde, l'exception partait dans
        # `View.on_error` — donc dans le `logging` standard, hors des sinks du
        # projet — et l'utilisateur restait sur un « Rangé » sans annonce.
        try:
            # `discord.File` OUVRE le fichier : bloquant, comme tout le reste ici.
            fichier = await asyncio.to_thread(discord.File, DOSSIER_MEMES / resultat.nom)
            await self.salon.send(
                f"📥 **{interaction.user.display_name}** a rangé un meme — `{resultat.nom}`",
                file=fichier,
            )
        except Exception as e:  # noqa: BLE001 — le fichier EST rangé, seule l'annonce manque
            logger.error("Annonce publique du meme {n} impossible : {e}", n=resultat.nom, e=e)
            await interaction.followup.send(
                content=(f"**{resultat.nom}** est bien rangé, mais l'annonce dans le "
                         f"salon n'a pas pu partir : {e}"),
                ephemeral=True,
            )
        self.stop()

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
        trouve = image_du_message(message)
        if trouve is None:
            await interaction.followup.send(
                content="Ce message ne porte aucune image.", ephemeral=True
            )
            return
        url, suffixe = trouve

        try:
            octets = await telecharger(url)
        except Exception as e:  # noqa: BLE001 — un CDN qui refuse ne casse rien
            logger.warning("Meme non rapatrié depuis {u} : {e}", u=url, e=e)
            await interaction.followup.send(
                content=f"Image impossible à récupérer : {e}", ephemeral=True
            )
            return

        try:
            deja = await asyncio.to_thread(meme_import.empreintes, DOSSIER_MEMES)
            depuis = deja.get(hashlib.sha256(octets).hexdigest())
            if depuis:
                await interaction.followup.send(
                    content=f"Déjà rangé sous **{depuis}**.", ephemeral=True
                )
                return

            description = ""
            analysable = suffixe in _EXTENSIONS
            vision = getattr(self.bot, "vision", None)
            if analysable and vision is not None and vision.available:
                description = tronquer_description(await vision.analyze(
                    [url], purpose="meme_describe", prompt_name="meme_describe_system"
                ) or "")

            reste = max(0, len(message.attachments) - 1)
            note = f"\n_{reste} autre(s) image(s) laissée(s)._" if reste else ""
            # Deux absences de description, deux causes : dire « pas d'analyse
            # pour une vidéo » devant un PNG que la vision n'a pas su décrire
            # envoie chercher un problème qui n'existe pas.
            if description:
                apercu = description
            elif analysable:
                apercu = "_(à écrire — l'analyse de l'image n'a rien rendu)_"
            else:
                apercu = f"_(à écrire — pas d'analyse possible sur un fichier {suffixe})_"
            vue = VueRangement(interaction.user.id, octets, suffixe, description, message.channel)
            vue.message = await interaction.followup.send(
                content=f"**Description proposée :**\n{apercu}{note}",
                view=vue,
                ephemeral=True,
                wait=True,
            )
        except Exception as e:  # noqa: BLE001 — un dossier illisible ne casse pas le bot
            logger.error("Aperçu de meme échoué : {e}", e=e)
            await interaction.followup.send(
                content=f"Erreur inattendue, rien n'a été rangé : {e}", ephemeral=True
            )
