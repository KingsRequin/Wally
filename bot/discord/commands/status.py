# bot/discord/commands/status.py
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.intelligence.identity import bot_name


class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="Statut du bot")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        uptime_s = int(time.time() - (self.bot._start_time or time.time()))
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s"

        daily_cost = await self.bot.image_client.get_daily_cost()
        monthly_cost = await self.bot.image_client.get_monthly_cost()

        dominant = self.bot.emotion.get_dominant(threshold=0.4)
        mood_str = ", ".join(dominant) if dominant else "neutre"

        embed = discord.Embed(title=f"Statut de {bot_name()}", color=discord.Color.blurple())
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Modele principal", value=f"{self.bot.config.llm.primary.provider}/{self.bot.config.llm.primary.model}", inline=True)
        embed.add_field(name="Humeur dominante", value=mood_str, inline=True)
        embed.add_field(name="Cout aujourd'hui", value=f"${daily_cost:.4f}", inline=True)
        embed.add_field(name="Cout ce mois", value=f"${monthly_cost:.4f}", inline=True)
        await interaction.followup.send(embed=embed)
