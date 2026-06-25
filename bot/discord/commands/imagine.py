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


def _load_phrases() -> list[str]:
    """Load loading phrases from file, one per line."""
    if not LOADING_PHRASES_FILE.exists():
        return [f"{bot_name()} peint..."]
    lines = [l.strip() for l in LOADING_PHRASES_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return lines or [f"{bot_name()} peint..."]


class GalleryView(discord.ui.View):
    """View with flame vote and edit title buttons for gallery images."""
    def __init__(self, image_id: str, creator_id: int, db):
        super().__init__(timeout=None)
        self.add_item(FlameButton(image_id, db))
        self.add_item(EditTitleButton(image_id, creator_id, db))


class FlameButton(discord.ui.Button):
    def __init__(self, image_id: str, db):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="🔥",
            label="0",
            custom_id=f"gallery_vote:{image_id}",
        )
        self.image_id = image_id
        self.db = db

    async def callback(self, interaction: discord.Interaction):
        user_id = f"discord:{interaction.user.id}"
        voted = await self.db.toggle_gallery_vote(self.image_id, user_id)
        image = await self.db.get_gallery_image(self.image_id)
        votes = image["votes"] if image else 0
        self.label = str(votes)
        self.style = discord.ButtonStyle.danger if voted else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self.view)


class EditTitleButton(discord.ui.Button):
    def __init__(self, image_id: str, creator_id: int, db):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="✏️",
            custom_id=f"gallery_edit:{image_id}",
        )
        self.image_id = image_id
        self.creator_id = creator_id
        self.db = db

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("Seul le créateur peut modifier le titre.", ephemeral=True)
            return
        modal = EditTitleModal(self.image_id, self.db)
        await interaction.response.send_modal(modal)


class EditTitleModal(discord.ui.Modal):
    new_title = discord.ui.TextInput(
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
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        if embed:
            embed.title = self.new_title.value.strip()
            await interaction.response.edit_message(embed=embed)
        else:
            await interaction.response.send_message("Titre mis à jour.", ephemeral=True)


class ImagineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="imagine", description="Génère une image à partir d'un prompt")
    @app_commands.describe(prompt="Description de l'image à générer")
    async def imagine(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        try:
            sender_id = f"discord:{interaction.user.id}"

            # Send loading embed with random GIF from local folder
            phrases = _load_phrases()
            loading_embed = discord.Embed(
                title=random.choice(phrases),
                description=f"*{prompt}*",
                color=discord.Color.from_str("#06b6d4"),
            )
            loading_embed.set_footer(text=f"Demandé par {interaction.user.display_name}")

            gifs = list(LOADING_GIFS_DIR.glob("*.gif"))
            loading_file = None
            if gifs:
                gif_path = random.choice(gifs)
                loading_file = discord.File(gif_path, filename="loading.gif")
                loading_embed.set_image(url="attachment://loading.gif")

            loading_msg = await interaction.followup.send(
                embed=loading_embed, file=loading_file, wait=True,
            )

            # Rotate loading phrases every 4 seconds
            rotate_done = asyncio.Event()

            async def _rotate_phrases():
                while not rotate_done.is_set():
                    await asyncio.sleep(5)
                    if rotate_done.is_set():
                        break
                    try:
                        loading_embed.title = random.choice(phrases)
                        await loading_msg.edit(embed=loading_embed)
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
                logger.warning("Failed to add image memory: {e}", e=e)

            # Build final embed with generated image
            from datetime import datetime
            embed = discord.Embed(
                title=title,
                description=f"*{prompt}*",
                color=discord.Color.from_str("#ffdd00"),
                timestamp=datetime.now(),
            )
            ext = result["file_name"].rsplit(".", 1)[-1]
            attach_name = f"image.{ext}"
            file = discord.File(result["file_path"], filename=attach_name)
            embed.set_image(url=f"attachment://{attach_name}")
            embed.set_footer(text=f"Par {interaction.user.display_name}")

            view = GalleryView(result["file_id"], interaction.user.id, self.bot.db)
            await loading_msg.edit(embed=embed, attachments=[file], view=view)

        except ValueError as e:
            await interaction.followup.send(f"❌ {e}")
        except Exception as e:
            logger.error("Error in /wally imagine: {e}", e=e)
            await interaction.followup.send("❌ Une erreur s'est produite lors de la génération.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle persistent gallery button interactions after bot restart."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")
        if not (custom_id.startswith("gallery_vote:") or custom_id.startswith("gallery_edit:")):
            return
        image_id = custom_id.split(":", 1)[1]
        if custom_id.startswith("gallery_vote:"):
            user_id = f"discord:{interaction.user.id}"
            voted = await self.bot.db.toggle_gallery_vote(image_id, user_id)
            image = await self.bot.db.get_gallery_image(image_id)
            votes = image["votes"] if image else 0
            view = GalleryView(image_id, 0, self.bot.db)
            view.children[0].label = str(votes)
            view.children[0].style = discord.ButtonStyle.danger if voted else discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=view)
        elif custom_id.startswith("gallery_edit:"):
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
