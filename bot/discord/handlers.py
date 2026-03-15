# bot/discord/handlers.py
from __future__ import annotations

import asyncio
import random
import re
from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

TIMEOUT_REACTIONS = ["💩", "⛔", "😤", "🙅", "😒"]

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def _fetch_discord_history(channel, limit: int, exclude_id: int | None = None) -> list[dict]:
    """Fallback cold start : récupère l'historique Discord via API.
    Retourne les messages en ordre chronologique (plus ancien en premier).
    Retourne [] en cas d'erreur (permissions, etc.).
    Note : dicts sans 'timestamp' — utilisés uniquement pour le prompt,
    non stockés dans _prelude_windows."""
    try:
        msgs = []
        async for m in channel.history(limit=limit + (1 if exclude_id is not None else 0)):
            if not m.author.bot and m.id != exclude_id:
                msgs.append({"author": m.author.display_name, "content": m.content})
        msgs.reverse()  # Discord renvoie du plus récent au plus ancien
        return msgs[-limit:] if len(msgs) > limit else msgs
    except Exception as e:
        logger.warning("channel.history() fallback failed: {e}", e=e)
        return []


async def handle_message(bot: "WallyDiscord", message: discord.Message) -> None:
    if message.author.bot:
        return

    # Capture passive + récupération prelude AVANT d'ajouter le message courant
    allowed = bot.config.discord.allowed_channels
    if not allowed or message.channel.id in allowed:
        prelude = bot.memory.get_prelude(str(message.channel.id))
        bot.memory.append_prelude(
            str(message.channel.id), message.author.display_name, message.content
        )
    else:
        prelude = []

    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    triggered = mentioned or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    if allowed and message.channel.id not in allowed:
        return

    user_id = str(message.author.id)
    guild_id = str(message.guild.id) if message.guild else "dm"

    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        return

    await _respond(bot, message, user_id, guild_id, prelude)
    _fire(_maybe_welcome(bot, message, user_id, guild_id))


_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)]) ")


def _is_list_item(line: str) -> bool:
    return bool(_LIST_RE.match(line))


async def _send_in_parts(message: discord.Message, text: str) -> None:
    """Split text on newlines, group consecutive list items, send as separate messages."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return

    # Group lines: consecutive list items are bundled into one message
    groups: list[str] = []
    current: list[str] = []
    in_list = False
    for line in lines:
        if _is_list_item(line):
            if not in_list:
                if current:
                    groups.append("\n".join(current))
                current = []
                in_list = True
            current.append(line)
        else:
            if in_list:
                groups.append("\n".join(current))
                current = []
                in_list = False
            current.append(line)
    if current:
        groups.append("\n".join(current))

    await message.reply(groups[0])
    for group in groups[1:]:
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await message.channel.send(group)


async def _respond(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
    prelude: list[dict],
) -> None:
    try:
        await message.add_reaction("🔍")

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, message.content)
        context_messages = await bot.memory.get_context_summarized_if_needed(
            str(message.channel.id)
        )

        # Fallback cold start si prelude vide
        if not prelude:
            prelude = await _fetch_discord_history(
                message.channel, bot.config.bot.prelude_window_size, exclude_id=message.id
            )

        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"

        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_messages)

        user_content = (
            prelude_block
            + context_block
            + f"\n[{message.author.display_name}]: {message.content}"
        )

        openai_messages = [{"role": "user", "content": user_content}]

        async with message.channel.typing():
            reply = await bot.openai.complete(
                system_prompt, openai_messages, purpose="discord_response"
            )

        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        await _send_in_parts(message, reply)

        bot.memory.append_message(
            str(message.channel.id), message.author.display_name, message.content
        )
        bot.memory.append_message(str(message.channel.id), "Wally", reply)

        exchange = f"[{message.author.display_name}]: {message.content}\n[Wally]: {reply}"
        _fire(bot.memory.add(platform, user_id, exchange))
        _fire(_post_process(bot, message.content, platform, user_id, guild_id, trust, context_messages))

    except Exception as e:
        logger.error("Error handling Discord message: {e}", e=e)
        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass


async def _post_process(
    bot: "WallyDiscord",
    text: str,
    platform: str,
    user_id: str,
    guild_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
) -> None:
    try:
        await bot.emotion.process_message(text, trust_score=trust, context_messages=context_messages)

        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)

        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8:
            count = await bot.db.count_recent_triggers(user_id, guild_id)
            if count >= bot.config.discord.anger_trigger_threshold:
                await bot.db.add_timeout(
                    user_id,
                    guild_id,
                    bot.config.discord.timeout_minutes,
                    anger,
                )
                logger.info(
                    "User {uid} muted for {m} minutes",
                    uid=user_id,
                    m=bot.config.discord.timeout_minutes,
                )
    except Exception as e:
        logger.error("Post-process error: {e}", e=e)


async def _maybe_welcome(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
) -> None:
    try:
        if await bot.db.is_welcomed(user_id, guild_id):
            return
        situation: dict = {"platform": "Discord"}
        if message.guild:
            situation["server"] = message.guild.name
        if isinstance(message.channel, discord.TextChannel):
            situation["channel"] = f"#{message.channel.name}"
        system_prompt = bot.prompts.build_system_prompt(
            bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
        )
        welcome = await bot.openai.complete(
            system_prompt,
            [
                {
                    "role": "user",
                    "content": (
                        f"C'est la première fois que {message.author.display_name} "
                        "écrit dans ce serveur. Envoie-lui un message de bienvenue "
                        "chaleureux et personnalisé."
                    ),
                }
            ],
            purpose="discord_welcome",
        )
        await message.channel.send(welcome)
        await bot.db.mark_welcomed(user_id, guild_id)
    except Exception as e:
        logger.error("Welcome error: {e}", e=e)
