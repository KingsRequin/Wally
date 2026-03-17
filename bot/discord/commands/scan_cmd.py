# bot/discord/commands/scan_cmd.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger


class ScanCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="scan",
        description="Analyse l'historique du salon et extrait les faits en mémoire (admin)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        messages="Nombre de messages à analyser (2–500)",
        heures="Durée en heures à couvrir (0.1–72)",
    )
    async def scan(
        self,
        interaction: discord.Interaction,
        messages: Optional[int] = None,
        heures: Optional[float] = None,
    ) -> None:
        # ── Validation (avant defer) ──────────────────────────────────────────
        if heures is None and messages is None:
            await interaction.response.send_message(
                "❌ Précise un nombre de messages ou une durée.", ephemeral=True
            )
            return

        if heures is not None and not (0.1 <= heures <= 72.0):
            await interaction.response.send_message(
                "❌ La durée doit être entre 0.1 et 72 heures.", ephemeral=True
            )
            return

        if heures is None and messages is not None and not (2 <= messages <= 500):
            await interaction.response.send_message(
                "❌ Le nombre de messages doit être entre 2 et 500.", ephemeral=True
            )
            return

        if getattr(self.bot, "session_manager", None) is None:
            await interaction.response.send_message(
                "❌ Service d'analyse non disponible.", ephemeral=True
            )
            return

        # ── Defer ────────────────────────────────────────────────────────────
        await interaction.response.defer(ephemeral=True)

        try:
            # ── Fetch historique ─────────────────────────────────────────────
            if heures is not None:
                after_dt = datetime.now(timezone.utc) - timedelta(hours=heures)
                fetched = [
                    m async for m in interaction.channel.history(
                        after=after_dt, oldest_first=True, limit=None
                    )
                ]
            else:
                fetched = [
                    m async for m in interaction.channel.history(
                        limit=messages, oldest_first=True
                    )
                ]

            # ── Analyse ──────────────────────────────────────────────────────
            stored = await self.bot.session_manager.analyze_channel_messages(
                messages=fetched,
                platform="discord",
                channel_id=str(interaction.channel_id),
                bot_user_id=interaction.client.user.id,
            )
            await interaction.followup.send(
                f"✅ Faits extraits pour {stored} utilisateur(s).", ephemeral=True
            )

        except ValueError:
            await interaction.followup.send(
                "⚠️ Pas assez de messages humains pour analyser (minimum 2).",
                ephemeral=True,
            )
        except discord.Forbidden:
            logger.warning("scan: Forbidden — permission lecture historique manquante")
            await interaction.followup.send(
                "❌ Je n'ai pas la permission de lire l'historique de ce salon.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            logger.error("scan: HTTPException lors du fetch: {e}", e=e)
            await interaction.followup.send(
                "❌ Erreur réseau lors du fetch. Consulte les logs.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("scan: erreur inattendue: {e}", e=e)
            await interaction.followup.send(
                "❌ Erreur lors de l'analyse. Consulte les logs.", ephemeral=True
            )
