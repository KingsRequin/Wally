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
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.core import meme_import
from bot.core.memes import _EXTENSIONS, _EXTENSIONS_MEDIA

DOSSIER_MEMES = Path("data/memes")

# Ce que l'aperçu laisse le temps de décider avant de se figer.
DELAI_APERCU = 120.0


def image_du_message(message) -> tuple[str, str] | None:
    """`(url, suffixe)` de la première image du message, ou None.

    Les pièces jointes d'abord ; à défaut l'image d'un embed, ce qui rattrape
    les liens Tenor ou Klipy postés sans fichier.
    """
    for a in message.attachments:
        if a.content_type and a.content_type.startswith(("image/", "video/")):
            suffixe = Path(urlparse(a.url).path).suffix.lower()
            if suffixe:
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


async def telecharger(url: str, limite: int = meme_import.MAX_TELECHARGEMENT) -> bytes:
    """Rapatrie l'image. Coupe net au-delà de la limite plutôt que de tout avaler."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as reponse:
            reponse.raise_for_status()
            morceaux: list[bytes] = []
            total = 0
            async for bloc in reponse.content.iter_chunked(64 * 1024):
                total += len(bloc)
                if total > limite:
                    raise ValueError(f"fichier au-delà de {limite / 1e6:.0f} Mo")
                morceaux.append(bloc)
    return b"".join(morceaux)


class FormulaireDescription(discord.ui.Modal, title="Description du meme"):
    """Le texte qui servira de vision à Wally — jamais affiché aux spectateurs."""

    def __init__(self, vue: "VueRangement") -> None:
        super().__init__()
        self._vue = vue
        self.description: discord.ui.TextInput = discord.ui.TextInput(
            label="Ce que Wally doit savoir de l'image",
            style=discord.TextStyle.paragraph,
            default=vue.description,
            required=False,
            max_length=400,
        )
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._vue.description = str(self.description.value).strip()
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
        await self.salon.send(
            f"📥 **{interaction.user.display_name}** a rangé un meme — `{resultat.nom}`",
            file=discord.File(DOSSIER_MEMES / resultat.nom),
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
            vision = getattr(self.bot, "vision", None)
            if suffixe in _EXTENSIONS and vision is not None and vision.available:
                description = await vision.analyze(
                    [url], purpose="meme_describe", prompt_name="meme_describe_system"
                ) or ""

            reste = max(0, len(message.attachments) - 1)
            note = f"\n_{reste} autre(s) image(s) laissée(s)._" if reste else ""
            apercu = description or "_(à écrire — pas d'analyse pour une vidéo)_"
            vue = VueRangement(interaction.user.id, octets, suffixe, description, message.channel)
            await interaction.followup.send(
                content=f"**Description proposée :**\n{apercu}{note}",
                view=vue,
                ephemeral=True,
            )
        except Exception as e:  # noqa: BLE001 — un dossier illisible ne casse pas le bot
            logger.error("Aperçu de meme échoué : {e}", e=e)
            await interaction.followup.send(
                content=f"Erreur inattendue, rien n'a été rangé : {e}", ephemeral=True
            )
