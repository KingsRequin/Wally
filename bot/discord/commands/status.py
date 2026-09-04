# bot/discord/commands/status.py
import time

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.discord.fiches import ACCENT_NEUTRE, fiche, url_avatar
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

        cfg = self.bot.config.llm.primary
        blocs = [
            f"**Debout depuis** {uptime_str}\n"
            f"**Modèle principal** `{cfg.provider}/{cfg.model}`\n"
            f"**Humeur dominante** {mood_str}",
            f"**Coût** {daily_cost:.4f} $ aujourd'hui · {monthly_cost:.4f} $ ce mois",
        ]

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
                blocs.append(
                    f"**Vocal restant ce mois**\n"
                    f"🎙️ {stt_h}h{stt_m:02d} d'écoute · {tts_k:.0f}k caractères de voix"
                )
            except Exception as e:  # noqa: BLE001 — le statut s'affiche même sans le quota
                # Le quota Azure F0 est plafonné (5 h de STT, 500 k car. de TTS
                # par mois) : c'est justement l'information qu'on veut voir
                # AVANT que la voix s'arrête. La faire disparaître sans un mot
                # la retire au moment où elle devient utile.
                logger.warning("Quota vocal illisible pour /status : {e!r}", e=e)

        await interaction.followup.send(view=fiche(
            f"Statut de {bot_name()}", blocs, accent=ACCENT_NEUTRE,
            vignette=url_avatar(self.bot.user),
        ))
