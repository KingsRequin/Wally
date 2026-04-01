# bot/discord/bot.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.core.persona import PersonaService


class WallyDiscord(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        llm: "BaseLLMClient",
        llm_secondary: "BaseLLMClient",
        image_client: "OpenAILLMClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        persona: "PersonaService",
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.llm = llm
        self.llm_secondary = llm_secondary
        self.image_client = image_client
        self.prompts = prompts
        self.language = language
        self.persona = persona
        self.journal = None  # set by main.py after construction
        self.graph = None  # set by main.py after construction
        self.social = None  # SocialTracker, set by main.py after construction
        self.fact_extractor = None  # set by main.py after construction
        self._start_time: float | None = None
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
        self.reaction_tracker = None  # set by main.py after construction

    async def setup_hook(self) -> None:
        from bot.discord.commands.ask import AskCog
        from bot.discord.commands.status import StatusCog
        from bot.discord.commands.mood import MoodCog
        from bot.discord.commands.memory_cmd import MemoryCog
        from bot.discord.commands.setup import SetupCog
        from bot.discord.commands.persona_cmd import PersonaCog
        from bot.discord.commands.journal_cmd import JournalCog
        from bot.discord.commands.scan_cmd import ScanCog
        from bot.discord.commands.test_cmd import TestCog
        from bot.discord.commands.imagine import ImagineCog

        await self.add_cog(AskCog(self))
        await self.add_cog(StatusCog(self))
        await self.add_cog(MoodCog(self))
        await self.add_cog(MemoryCog(self))
        await self.add_cog(SetupCog(self))
        await self.add_cog(PersonaCog(self))
        await self.add_cog(JournalCog(self))
        await self.add_cog(ScanCog(self))
        await self.add_cog(TestCog(self))
        await self.add_cog(ImagineCog(self))

        # Sync slash commands — wrap in try/except so a 403 (bot not yet in guild) doesn't crash startup
        try:
            import os
            guild_id = int(os.getenv("DISCORD_GUILD_ID", "0")) or None
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            await self.tree.sync()
            logger.info("Discord slash commands synced")
        except discord.Forbidden:
            logger.warning("Discord slash commands sync skipped — bot not yet in guild (invite it first)")
        except Exception as e:
            logger.warning("Discord slash commands sync failed: {}", e)

    async def on_ready(self) -> None:
        self._start_time = time.time()
        logger.info("Discord bot ready as {user}", user=self.user)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not self.reaction_tracker:
            return
        if payload.user_id == self.user.id:
            return
        member = payload.member
        is_bot = member.bot if member else False
        self.reaction_tracker.record_discord_reaction(
            payload.message_id, str(payload.emoji), is_bot,
        )

    async def on_voice_state_update(self, member, before, after) -> None:
        if member.bot or not self.social:
            return
        if before.channel != after.channel:
            if before.channel:
                self.social.on_voice_leave(before.channel.id, member.id, member.display_name)
            if after.channel:
                self.social.on_voice_join(after.channel.id, member.id, member.display_name)

    async def on_reaction_add(self, reaction, user) -> None:
        if user.bot or not self.social:
            return
        if reaction.message.author != user:
            self.social.on_reaction(user.display_name, reaction.message.author.display_name)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("update_instance_"):
            return
        slug = custom_id[len("update_instance_"):]
        if not interaction.guild:
            await interaction.response.send_message("Commande disponible uniquement dans un serveur.", ephemeral=True)
            return
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.guild_permissions.manage_guild:
            await interaction.response.send_message("Permission insuffisante (Gérer le serveur requis).", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            from bot.core.provisioner import INSTANCES_DIR
            compose_path = INSTANCES_DIR / slug / "docker-compose.yml"
            if not compose_path.exists():
                await interaction.followup.send(f"Instance `{slug}` introuvable.", ephemeral=True)
                return
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/docker", "compose", "-f", str(compose_path),
                "up", "-d", "--force-recreate",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0:
                logger.info("Instance {} updated via Discord button by {}", slug, interaction.user)
                await interaction.followup.send(f"Instance `{slug}` mise a jour !", ephemeral=True)
                try:
                    await interaction.message.edit(
                        content=interaction.message.content + f"\nMis a jour par {interaction.user.display_name}"
                    )
                except Exception:
                    pass
            else:
                await interaction.followup.send(f"Erreur : {stderr.decode()[:300]}", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("Timeout lors de la mise a jour (>60s).", ephemeral=True)
        except Exception as exc:
            logger.error("Update instance {} failed: {}", slug, exc)
            await interaction.followup.send(f"Erreur : {exc}", ephemeral=True)

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        logger.exception("Discord error in {e}", e=event_method)
