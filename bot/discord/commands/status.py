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

        # Quota vocal Azure (free tier) restant ce mois — seulement si le vocal est activé.
        voice_cfg = getattr(self.bot.config, "voice", None)
        if voice_cfg is not None and getattr(voice_cfg, "enabled", False):
            try:
                vs = getattr(self.bot, "voice_service", None)
                if vs is not None and getattr(vs, "quota", None) is not None:
                    snap = vs.quota.snapshot()
                else:
                    from bot.discord.voice.quota import VoiceQuota
                    snap = VoiceQuota().snapshot()
                stt_h, _r = divmod(int(snap["stt_remaining_seconds"]), 3600)
                stt_m = _r // 60
                tts_k = snap["tts_remaining_chars"] / 1000
                embed.add_field(
                    name="Vocal restant (ce mois)",
                    value=f"🎙️ {stt_h}h{stt_m:02d} d'écoute · {tts_k:.0f}k caractères de voix",
                    inline=False,
                )
            except Exception:  # noqa: BLE001
                pass
        await interaction.followup.send(embed=embed)
