# bot/discord/commands/memory_cmd.py
"""`/wally memory` : ce que le bot retient de quelqu'un.

La fiche est en **Components V2** : un `Container` qui porte le titre, les
scores de relation, le texte de la page et les flèches. Ce que la bascule
change pour de bon : confiance et affection ne sont plus COLLÉES en tête du
texte paginé — elles vivaient dans la page 1 et disparaissaient dès qu'on
tournait la page, alors qu'elles décrivent la personne entière.
"""
import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.intelligence.identity import bot_name

_PAGE_SIZE = 1800  # caractères par page (marge sous le plafond V2 de 4000 par message)
_COULEUR = 0x22C55E   # le vert « curiosity » du dashboard


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


class _Fleche(discord.ui.Button):
    """Une page en arrière ou en avant. `pas` vaut -1 ou +1."""

    def __init__(self, vue: "VueMemoire", label: str, pas: int, *, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary,
                         disabled=disabled)
        self.vue = vue
        self.pas = pas

    async def callback(self, interaction: discord.Interaction) -> None:
        self.vue.page += self.pas
        # La vue se REBÂTIT : en Components V2 les flèches sont dans le
        # conteneur, donc changer de page change tout l'arbre, pas un embed.
        await interaction.response.edit_message(view=self.vue.rebatie())


class VueMemoire(discord.ui.LayoutView):
    """La fiche mémoire d'une personne, page par page."""

    def __init__(self, pages: list[str], user_name: str, trust: float,
                 love: float, page: int = 0):
        super().__init__(timeout=180)
        self.pages = pages
        self.user_name = user_name
        self.trust = trust
        self.love = love
        self.page = max(0, min(page, len(pages) - 1))
        self._batir()

    def rebatie(self) -> "VueMemoire":
        return VueMemoire(self.pages, self.user_name, self.trust, self.love,
                          self.page)

    def _batir(self) -> None:
        suffix = (f" ({self.page + 1}/{len(self.pages)})"
                  if len(self.pages) > 1 else "")
        contenu: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                f"## Mémoire de {bot_name()}, {self.user_name}{suffix}"),
            discord.ui.TextDisplay(
                f"-# 🛡️ Confiance : {self.trust:.2f}  ❤️ Affection : {self.love:.2f}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(self.pages[self.page]),
        ]
        if len(self.pages) > 1:
            contenu.append(discord.ui.ActionRow(
                _Fleche(self, "◀", -1, disabled=self.page == 0),
                _Fleche(self, "▶", +1,
                        disabled=self.page >= len(self.pages) - 1),
            ))
        self.add_item(discord.ui.Container(
            *contenu, accent_colour=discord.Colour(_COULEUR)))


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

            # Sans souvenir, la fiche vaut quand même : confiance et affection
            # existent dès la première interaction.
            pages = _paginate(mem) if mem else ["*Aucun souvenir.*"]
            vue = VueMemoire(pages, target.display_name, trust, love)
            await interaction.followup.send(view=vue, ephemeral=True)
        except Exception as e:
            logger.error("Memory show error: {e!r}", e=e)
            await interaction.followup.send(
                "Erreur lors de la lecture de la memoire.", ephemeral=True
            )
