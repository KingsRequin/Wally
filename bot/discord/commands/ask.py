# bot/discord/commands/ask.py
import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from bot.discord.handlers import _post_process


class AskCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ask", description="Pose une question directement à Wally")
    @app_commands.describe(question="Ta question pour Wally")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        try:
            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild_id) if interaction.guild_id else "dm"
            platform = "discord"

            trust = await self.bot.db.get_trust_score(platform, user_id)
            mem_context = await self.bot.memory.search(platform, user_id, question)
            context_msgs = await self.bot.memory.get_context_summarized_if_needed(
                str(interaction.channel_id)
            )

            situation: dict = {"platform": "Discord"}
            if interaction.guild:
                situation["server"] = interaction.guild.name
            if interaction.channel and hasattr(interaction.channel, "name"):
                situation["channel"] = f"#{interaction.channel.name}"

            system_prompt = self.bot.prompts.build_system_prompt(
                emotion_state=self.bot.emotion.get_state(),
                memory_context=mem_context,
                situation=situation,
                persona_block=self.bot.persona.build_prompt_block(),
                emotion_directives=self.bot.persona.emotion_directives,
            )
            context_block = self.bot.prompts.build_context_block(context_msgs)

            if context_block:
                content = (
                    context_block + f"\n[{interaction.user.display_name}]: {question}"
                )
            else:
                content = question

            reply = await self.bot.openai.complete(
                system_prompt,
                [{"role": "user", "content": content}],
                purpose="discord_ask",
            )

            self.bot.memory.append_message(
                str(interaction.channel_id), interaction.user.display_name, question
            )
            self.bot.memory.append_message(str(interaction.channel_id), "Wally", reply)

            asyncio.create_task(
                _post_process(self.bot, question, platform, user_id, guild_id, trust)
            )
            await interaction.followup.send(reply)

        except Exception as e:
            logger.error("Error in /wally ask: {e}", e=e)
            await interaction.followup.send("Une erreur s'est produite.")
