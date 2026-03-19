# bot/discord/handlers.py
from __future__ import annotations

import asyncio
import json
import random
import re
import re as _re
import time
from typing import TYPE_CHECKING

import discord
from loguru import logger

if TYPE_CHECKING:
    from bot.discord.bot import WallyDiscord

TIMEOUT_REACTIONS = ["💩", "⛔", "😤", "🙅", "😒"]

_REACT_TAG_RE = _re.compile(r"^\[react:(.+?)\]\s*")

_LAUGH_WORDS = {"mdr", "lol", "ptdr", "xd", "haha", "😂", "🤣"}
_POSITIVE_WORDS = {"gg", "bravo", "trop bien", "bien joué", "incroyable"}
_NEGATIVE_WORDS = {"merde", "putain", "nul", "chier"}

_LAUGH_EMOJIS = ("😂", "💀")
_POSITIVE_EMOJIS = ("🔥", "👏")
_NEGATIVE_EMOJIS = ("😤", "💀")


def _parse_react_tag(text: str) -> tuple[str | None, str]:
    """Parse un tag [react:emoji] au début du texte.
    Retourne (emoji, texte_nettoyé) ou (None, texte_original).
    """
    m = _REACT_TAG_RE.match(text)
    if m:
        return m.group(1), text[m.end():].strip()
    return None, text


def _pick_passive_emoji(text: str, curiosity: float) -> str | None:
    """Choisit un emoji de réaction passive basé sur le contenu du message.
    Retourne None si aucun signal détecté.
    """
    text_lower = text.lower()
    if any(w in text_lower for w in _LAUGH_WORDS):
        return random.choice(_LAUGH_EMOJIS)
    if any(w in text_lower for w in _POSITIVE_WORDS):
        return random.choice(_POSITIVE_EMOJIS)
    if any(w in text_lower for w in _NEGATIVE_WORDS):
        return random.choice(_NEGATIVE_EMOJIS)
    if curiosity >= 0.4 and "?" in text:
        return "🤔"
    return None


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


def _is_channel_allowed(config, channel_id: int) -> bool:
    """Vérifie si Wally peut répondre dans ce canal selon le mode de filtrage."""
    mode = config.discord.channel_filter_mode
    if mode == "whitelist":
        wl = config.discord.channel_whitelist
        return not wl or channel_id in wl
    if mode == "blacklist":
        bl = config.discord.channel_blacklist
        return channel_id not in bl
    return True  # mode "none" ou inconnu : tout autorisé


async def handle_message(bot: "WallyDiscord", message: discord.Message) -> None:
    if message.author.bot:
        return

    # Dashboard message counter
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1

    user_id = str(message.author.id)
    channel_allowed = _is_channel_allowed(bot.config, message.channel.id)

    # Capture passive + récupération prelude AVANT d'ajouter le message courant
    if channel_allowed:
        prelude = bot.memory.get_prelude(str(message.channel.id))
        bot.memory.append_prelude(
            str(message.channel.id), message.author.display_name, message.content
        )
        # Enregistrement dans la session active du canal (tous les messages)
        if getattr(bot, "session_manager", None) is not None:
            bot.session_manager.record_message(
                str(message.channel.id),
                "discord",
                user_id,
                message.author.display_name,
                message.content,
            )
    else:
        prelude = []

    # Reaction tracking: detect positive replies to Wally's messages
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker and message.reference and message.reference.message_id:
        tracker.record_discord_reply(
            message.reference.message_id, message.content, message.author.bot,
        )

    content_lower = message.content.lower()
    mentioned = bot.user in message.mentions
    triggered = mentioned or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        # Passive emoji reaction on non-trigger messages (Discord only)
        if channel_allowed and random.random() < bot.config.discord.emoji_reaction_probability:
            curiosity = bot.emotion.get_state().get("curiosity", 0.0)
            passive_emoji = _pick_passive_emoji(message.content, curiosity)
            if passive_emoji:
                try:
                    await message.add_reaction(passive_emoji)
                except Exception:
                    pass
        return

    if not channel_allowed:
        return

    guild_id = str(message.guild.id) if message.guild else "dm"

    if await bot.db.is_muted(user_id, guild_id):
        emoji = random.choice(TIMEOUT_REACTIONS)
        await message.add_reaction(emoji)
        return

    first_contact = not await bot.db.is_welcomed(user_id, guild_id)
    await _respond(bot, message, user_id, guild_id, prelude, first_contact=first_contact)


_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)]) ")


def _is_list_item(line: str) -> bool:
    return bool(_LIST_RE.match(line))


async def _send_in_parts(message: discord.Message, text: str) -> int | None:
    """Split text on newlines, group consecutive list items, send as separate messages."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return None

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

    first_msg = await message.reply(groups[0])
    for group in groups[1:]:
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await message.channel.send(group)
    return first_msg.id


async def _respond(
    bot: "WallyDiscord",
    message: discord.Message,
    user_id: str,
    guild_id: str,
    prelude: list[dict],
    first_contact: bool = False,
) -> None:
    try:
        await message.add_reaction("🔍")

        platform = "discord"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, message.content, context_messages=prelude)

        # Temporal activity: inject absence note if user hasn't been seen in 7+ days
        try:
            last_seen = await bot.db.get_last_interaction(f"{platform}:{user_id}")
            if last_seen:
                days_ago = int((time.time() - last_seen) / 86400)
                if days_ago >= 7:
                    absence_note = f"\nDernière interaction avec cet utilisateur : il y a {days_ago} jours."
                    mem_context = (mem_context + absence_note) if mem_context else absence_note.strip()
        except Exception:
            pass

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
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_messages)

        # Extraction des images
        image_urls = [
            a.url for a in message.attachments
            if a.content_type and a.content_type.startswith("image/")
        ][:4]

        # Texte à envoyer (substitution si message image-only)
        text_content = message.content or ("Regarde cette image." if image_urls else "")

        user_content = (
            prelude_block
            + context_block
            + f"\n[{message.author.display_name}]: {text_content}"
        )

        if first_contact:
            user_content = (
                f"[CONTEXTE: C'est la première fois que {message.author.display_name} "
                f"t'adresse la parole sur ce serveur. Commence ta réponse par une "
                f"bienvenue chaleureuse en une phrase courte, puis réponds à son message.]\n\n"
                + user_content
            )

        openai_messages = [{"role": "user", "content": user_content}]

        # ── Collect available tools ──────────────────────────────────────
        tools: list[dict] = []
        web_search = getattr(bot, "web_search", None)
        if web_search and web_search.available and not await web_search.is_quota_exceeded():
            tools.extend(web_search.get_tool_definitions())
        apex_api = getattr(bot, "apex_api", None)
        if apex_api and apex_api.available:
            tools.append(apex_api.get_tool_definition())

        _reaction_emojis: set[str] = set()

        async def _tool_executor(name: str, arguments: str) -> str:
            args = json.loads(arguments)
            if name in ("web_search", "image_search"):
                if "🌐" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🌐")
                        _reaction_emojis.add("🌐")
                    except Exception:
                        pass
                if name == "image_search":
                    return await web_search.search_images(args["query"])
                return await web_search.search(args["query"])
            if name == "apex_legends":
                if "🔫" not in _reaction_emojis:
                    try:
                        await message.add_reaction("🔫")
                        _reaction_emojis.add("🔫")
                    except Exception:
                        pass
                return await apex_api.execute(
                    args.get("action", ""),
                    player_name=args.get("player_name", ""),
                    platform=args.get("platform", "PC"),
                )
            return f"Unknown tool: {name}"

        async with message.channel.typing():
            if tools:
                reply, tools_called = await bot.openai.complete_with_tools(
                    system_prompt, openai_messages, tools, _tool_executor,
                    purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
            else:
                reply = await bot.openai.complete(
                    system_prompt, openai_messages, purpose="discord_response",
                    image_urls=image_urls or None,
                    user_id=f"discord:{message.author.id}",
                )
                tools_called = []

        # Parse optional [react:emoji] tag from LLM response
        react_emoji, reply = _parse_react_tag(reply)

        try:
            await message.remove_reaction("🔍", bot.user)
        except Exception:
            pass
        for emoji in _reaction_emojis:
            try:
                await message.remove_reaction(emoji, bot.user)
            except Exception:
                pass

        if react_emoji:
            try:
                await message.add_reaction(react_emoji)
            except Exception:
                pass

        reply_msg_id = await _send_in_parts(message, reply)
        if reply_msg_id and getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_discord_message(reply_msg_id)

        if first_contact:
            await bot.db.mark_welcomed(user_id, guild_id)

        stored_content = message.content or "[image]"
        bot.memory.append_message(
            str(message.channel.id), message.author.display_name, stored_content, platform="discord"
        )
        bot.memory.append_message(str(message.channel.id), "Wally", reply, platform="discord")

        # Persiste le display_name pour que le dashboard coûts affiche un nom lisible
        await bot.db.upsert_memory_user(
            f"discord:{message.author.id}", "discord",
            username=message.author.display_name,
        )

        _fire(_post_process(
            bot, text_content, platform, user_id, guild_id, trust, context_messages,
            image_urls=image_urls or None,
            channel_id=str(message.channel.id),
        ))

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
    image_urls: list[str] | None = None,
    channel_id: str = "",
) -> None:
    try:
        await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            image_urls=image_urls,
            trigger_user=user_id, channel_id=channel_id, platform="discord",
        )

        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)

        anger = bot.emotion.get_state().get("anger", 0.0)
        if anger >= 0.8:
            # Always record the anger trigger (duration=0 → tracking only, not a real mute)
            await bot.db.add_timeout(user_id, guild_id, 0, anger)
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


