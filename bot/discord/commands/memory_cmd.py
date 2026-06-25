# bot/discord/commands/memory_cmd.py
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.intelligence.identity import bot_name

_PAGE_SIZE = 1800  # caractères par page (marge sous la limite Discord de 2000)


def _paginate(text: str) -> list[str]:
    """Découpe le texte en pages de _PAGE_SIZE caractères max sur des coupures de lignes."""
    if len(text) <= _PAGE_SIZE:
        return [text]
    pages: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = (current + "\n" + line).strip()
        if len(candidate) <= _PAGE_SIZE:
            current = candidate
        else:
            if current:
                pages.append(current)
            current = line
    if current:
        pages.append(current)
    return pages or [text[:_PAGE_SIZE]]


class MemoryPaginatedView(discord.ui.View):
    def __init__(self, pages: list[str], user_name: str):
        super().__init__(timeout=180)
        self.pages = pages
        self.user_name = user_name
        self.current = 0
        self._sync_buttons()

    def _make_embed(self) -> discord.Embed:
        suffix = f" ({self.current + 1}/{len(self.pages)})" if len(self.pages) > 1 else ""
        return discord.Embed(
            title=f"Mémoire de {bot_name()} — {self.user_name}{suffix}",
            description=self.pages[self.current],
            color=discord.Color.green(),
        )

    def _sync_buttons(self) -> None:
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._make_embed(), view=self)


class MemoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="memory", description="Ce que le bot retient de toi")
    @app_commands.describe(user="(Admin) Voir la mémoire d'un autre utilisateur")
    async def memory_show(self, interaction: discord.Interaction, user: discord.Member | None = None):
        # Voir les souvenirs de quelqu'un d'autre → admin requis
        if user is not None and user.id != interaction.user.id:
            perms = interaction.user.guild_permissions if interaction.guild else None
            if not (perms and perms.administrator):
                await interaction.response.send_message(
                    "Seuls les admins peuvent voir la mémoire d'un autre utilisateur.",
                    ephemeral=True,
                )
                return

        target = user or interaction.user
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            mem = await self.bot.memory.get_all("discord", str(target.id))
            trust = await self.bot.db.get_trust_score("discord", str(target.id))
            love = await self.bot.db.get_love_score("discord", str(target.id), self.bot.config.bot.love_decay_lambda)

            # Prepend trust + love to memory text
            header = f"🛡️ Confiance : {trust:.2f}  ❤️ Affection : {love:.2f}\n\n"

            if not mem:
                # Still show trust+love even with no memories
                await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"Mémoire de {bot_name()} — {target.display_name}",
                        description=f"🛡️ Confiance : {trust:.2f}  ❤️ Affection : {love:.2f}\n\nAucun souvenir.",
                        color=discord.Color.green(),
                    ),
                    ephemeral=True,
                )
                return
            pages = _paginate(header + mem)
            view = MemoryPaginatedView(pages, target.display_name)
            await interaction.followup.send(
                embed=view._make_embed(), view=view, ephemeral=True
            )
        except Exception as e:
            logger.error("Memory show error: {e}", e=e)
            await interaction.followup.send(
                "Erreur lors de la lecture de la memoire.", ephemeral=True
            )
