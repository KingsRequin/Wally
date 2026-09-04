import asyncio
import random
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.intelligence.identity import bot_name

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
LOADING_GIFS_DIR = DATA_DIR / "loading_gifs"
LOADING_PHRASES_FILE = DATA_DIR / "loading_phrases.txt"

NOM_GIF = "loading.gif"
_COULEUR_ATTENTE = 0x06B6D4       # cyan d'accent du dashboard
_COULEUR_IMAGE = 0xFFDD00
_PREFIXE_VOTE = "gallery_vote:"
_PREFIXE_TITRE = "gallery_edit:"


def _load_phrases() -> list[str]:
    """Load loading phrases from file, one per line."""
    if not LOADING_PHRASES_FILE.exists():
        return [f"{bot_name()} peint..."]
    lines = [l.strip() for l in LOADING_PHRASES_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return lines or [f"{bot_name()} peint..."]


def _nom_piece_jointe(file_name: str) -> str:
    """`abc123.png` → `image.png`. Le nom posté à l'envoi, redéduit au clic.

    La pièce jointe survit aux éditions qui ne la renvoient pas : c'est ce qui
    permet de redessiner la carte sur un simple vote, sans relire le PNG.
    """
    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "png"
    return f"image.{ext}"


class FlameButton(discord.ui.Button):
    """Le 🔥 d'une image : son libellé EST le compteur de flammes.

    Le style ne change JAMAIS. Il passait en `danger` quand la dernière personne
    qui avait cliqué venait de voter — sur un message que tout le monde voit,
    ce rouge annonçait aux autres un vote qui n'était pas le leur, et il
    repartait au gris après un rebuild. Le retour d'un clic, c'est le compteur.
    """

    def __init__(self, image_id: str, votes: int = 0):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="🔥",
            label=str(votes),
            custom_id=f"{_PREFIXE_VOTE}{image_id}",
        )
        self.image_id = image_id

    # Pas de `callback` : voir `VueGalerie`. Le clic est traité une seule fois,
    # par `ImagineCog.on_interaction`.


class EditTitleButton(discord.ui.Button):
    def __init__(self, image_id: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="✏️",
            custom_id=f"{_PREFIXE_TITRE}{image_id}",
        )
        self.image_id = image_id

    # Pas de `callback` : voir `VueGalerie`. Le listener relit le créateur depuis
    # la base, ce qui vaut aussi après un redémarrage — là où `creator_id` vaut 0.


class VueChargement(discord.ui.LayoutView):
    """Ce qu'on voit pendant que le modèle peint.

    Envoyée en Components V2 dès le PREMIER message, et pas seulement à
    l'arrivée de l'image : le drapeau `IS_COMPONENTS_V2` s'ajoute à l'édition
    mais ne se retire plus, et Discord refuse un message V2 qui garde un embed.
    Partir en V2 supprime toute bascule à mi-chemin.
    """

    def __init__(self, phrase: str, prompt: str, auteur: str, *, gif: bool):
        super().__init__(timeout=None)
        contenu: list[discord.ui.Item] = [
            discord.ui.TextDisplay(f"## {phrase}"),
            discord.ui.TextDisplay(f"*{prompt}*"),
        ]
        if gif:
            galerie: discord.ui.MediaGallery = discord.ui.MediaGallery()
            galerie.add_item(media=f"attachment://{NOM_GIF}")
            contenu.append(galerie)
        contenu.append(discord.ui.TextDisplay(f"-# Demandé par {auteur}"))
        self.add_item(discord.ui.Container(
            *contenu, accent_colour=discord.Colour(_COULEUR_ATTENTE)))


class VueGalerie(discord.ui.LayoutView):
    """La carte d'une image : titre, prompt, image, flammes et crayon.

    Les boutons vivent DANS le conteneur, sous l'image : en Components V2 une
    `ActionRow` est un composant comme un autre, et les coller à la carte évite
    la rangée orpheline que Discord détachait sous l'embed.
    """

    def __init__(self, image_id: str, titre: str, prompt: str, auteur: str,
                 piece_jointe: str, votes: int = 0):
        super().__init__(timeout=None)
        galerie: discord.ui.MediaGallery = discord.ui.MediaGallery()
        galerie.add_item(media=f"attachment://{piece_jointe}")
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"## {titre}"),
            discord.ui.TextDisplay(f"*{prompt}*"),
            galerie,
            discord.ui.ActionRow(FlameButton(image_id, votes),
                                 EditTitleButton(image_id)),
            discord.ui.TextDisplay(f"-# Par {auteur}"),
            accent_colour=discord.Colour(_COULEUR_IMAGE),
        ))


def vue_depuis_base(image: dict) -> VueGalerie:
    """Rebâtit la carte à partir de la LIGNE en base, jamais du message affiché.

    Un clic n'arrive pas toujours dans le process qui a posté l'image : après un
    rebuild, `creator_id` valait 0 et le titre n'existait plus qu'à l'écran. La
    base porte tout ce qu'il faut — y compris le nom de la pièce jointe, déduit
    de `file_path`, qui reste attachée au message tant qu'on ne la remplace pas.
    """
    return VueGalerie(
        str(image["id"]),
        str(image.get("title") or "Sans titre"),
        str(image.get("prompt") or ""),
        str(image.get("username") or "?"),
        _nom_piece_jointe(str(image.get("file_path") or "image.png")),
        int(image.get("votes") or 0),
    )


class EditTitleModal(discord.ui.Modal):
    new_title: discord.ui.TextInput = discord.ui.TextInput(
        label="Nouveau titre",
        placeholder="Titre de l'image...",
        max_length=100,
        required=True,
    )

    def __init__(self, image_id: str, db):
        super().__init__(title="Modifier le titre")
        self.image_id = image_id
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await self.db.update_gallery_title(self.image_id, self.new_title.value.strip())
        image = await self.db.get_gallery_image(self.image_id)
        if image is None:
            # La ligne a disparu entre le clic et l'envoi du modal : redessiner
            # la carte reviendrait à inventer son contenu.
            await interaction.response.send_message("Image introuvable.", ephemeral=True)
            return
        await interaction.response.edit_message(view=vue_depuis_base(image))


class ImagineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="imagine", description="Génère une image à partir d'un prompt")
    @app_commands.describe(prompt="Description de l'image à générer")
    async def imagine(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        try:
            sender_id = f"discord:{interaction.user.id}"

            phrases = _load_phrases()
            gifs = list(LOADING_GIFS_DIR.glob("*.gif"))
            loading_file = None
            if gifs:
                loading_file = discord.File(random.choice(gifs), filename=NOM_GIF)

            def _vue_attente() -> VueChargement:
                return VueChargement(random.choice(phrases), prompt,
                                     interaction.user.display_name,
                                     gif=loading_file is not None)

            loading_msg = await interaction.followup.send(
                view=_vue_attente(), file=loading_file, wait=True,
            )

            # Rotate loading phrases every 5 seconds
            rotate_done = asyncio.Event()

            async def _rotate_phrases():
                while not rotate_done.is_set():
                    await asyncio.sleep(5)
                    if rotate_done.is_set():
                        break
                    try:
                        # Sans `attachments=`, le GIF déjà posté reste en place :
                        # la référence `attachment://` continue de se résoudre.
                        await loading_msg.edit(view=_vue_attente())
                    except Exception:
                        # Rate limit probable, attendre plus longtemps avant de réessayer
                        await asyncio.sleep(6)

            rotate_task = asyncio.create_task(_rotate_phrases())

            # Generate image
            try:
                result = await self.bot.image_client.generate_image(prompt, self.bot.config.image_generation, sender_id)
            finally:
                rotate_done.set()
                rotate_task.cancel()

            # Generate short title
            title = await self.bot.llm_secondary.complete(
                "Tu es un assistant. Génère un titre court et créatif (max 6 mots) pour cette image. "
                "Réponds UNIQUEMENT avec le titre, rien d'autre.",
                [{"role": "user", "content": f"Image générée à partir du prompt : {prompt}"}],
                purpose="image_title",
            )
            title = title.strip().strip('"').strip("'")[:100]

            # Insert in gallery
            await self.bot.db.insert_gallery_image(
                id=result["file_id"],
                title=title,
                prompt=prompt,
                revised_prompt=result.get("revised_prompt"),
                username=interaction.user.display_name,
                user_id=str(interaction.user.id),
                platform="discord",
                file_path=result["file_name"],
                model=result["model"],
                quality=result["quality"],
                size=result["size"],
                cost_usd=result["cost_usd"],
            )

            # Memory
            try:
                from bot.discord.handlers import _channel_origin
                await self.bot.memory.add(
                    "discord", str(interaction.user.id),
                    f"{interaction.user.display_name} a généré une image : {title}",
                    username=interaction.user.display_name,
                    origin=_channel_origin(interaction.channel),
                )
            except Exception as e:
                logger.warning("Failed to add image memory: {e!r}", e=e)

            attach_name = _nom_piece_jointe(result["file_name"])
            file = discord.File(result["file_path"], filename=attach_name)
            vue = VueGalerie(result["file_id"], title, prompt,
                             interaction.user.display_name, attach_name)
            await loading_msg.edit(view=vue, attachments=[file])

        except ValueError as e:
            await interaction.followup.send(f"❌ {e}")
        except Exception as e:
            logger.error("Error in /wally imagine: {e!r}", e=e)
            await interaction.followup.send("❌ Une erreur s'est produite lors de la génération.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle persistent gallery button interactions after bot restart."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if not (custom_id.startswith(_PREFIXE_VOTE) or custom_id.startswith(_PREFIXE_TITRE)):
            return
        image_id = custom_id.split(":", 1)[1]
        if custom_id.startswith(_PREFIXE_VOTE):
            user_id = f"discord:{interaction.user.id}"
            await self.bot.db.toggle_gallery_vote(image_id, user_id)
            image = await self.bot.db.get_gallery_image(image_id)
            if image is None:
                await interaction.response.send_message("Image introuvable.", ephemeral=True)
                return
            await interaction.response.edit_message(view=vue_depuis_base(image))
        elif custom_id.startswith(_PREFIXE_TITRE):
            image = await self.bot.db.get_gallery_image(image_id)
            if not image:
                await interaction.response.send_message("Image introuvable.", ephemeral=True)
                return
            creator_discord_id = int(image["user_id"].replace("discord:", ""))
            if interaction.user.id != creator_discord_id:
                await interaction.response.send_message("Seul le créateur peut modifier le titre.", ephemeral=True)
                return
            modal = EditTitleModal(image_id, self.bot.db)
            await interaction.response.send_modal(modal)
