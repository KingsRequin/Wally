# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def handle_message(bot: "WallyTwitch", payload) -> None:
    """Handle an incoming channel.chat.message EventSub payload."""
    # Dashboard message counter (tous les messages, pas seulement les triggers)
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1

    content: str = payload.message.text
    content_lower = content.lower()
    author: str = payload.chatter.name
    user_id: str = str(payload.chatter.id)
    # Normalisé en minuscules — cohérent avec les clés de _channel_ids
    channel_name: str = payload.broadcaster.name.lower()
    channel_id = f"twitch:{channel_name}"

    # Marquer la chaîne invitée comme "vue live" dès réception d'un message
    if channel_name in bot._channel_ids:
        bot._channel_was_live[channel_name] = True

    # Ignorer les propres messages de Wally qui reviennent via EventSub
    bot_id = str(getattr(bot.twitch_api, "_bot_id", ""))
    if bot_id and user_id == bot_id:
        return

    # Capture passive : prelude AVANT d'ajouter le message courant
    prelude = bot.memory.get_prelude(channel_id)
    bot.memory.append_prelude(channel_id, author, content)
    if getattr(bot, "session_manager", None) is not None:
        bot.session_manager.record_message(channel_id, "twitch", user_id, author, content)

    # Reaction tracking: scan for positive reactions in Twitch window
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker:
        tracker.check_twitch_message(channel_id, content)

    # Trigger check
    bot_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
    triggered = (bot_nick and f"@{bot_nick}" in content_lower) or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    if bot.is_on_cooldown(user_id):
        return

    try:
        platform = "twitch"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude)
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        situation = {
            "platform": "Twitch",
            "streamer": channel_name,
            "channel": f"#{channel_name}",
        }
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
        context_block = bot.prompts.build_context_block(context_msgs)
        user_content = prelude_block + context_block + f"\n[{author}]: {content}"

        openai_messages = [{"role": "user", "content": user_content}]

        # ── Collect available tools ──────────────────────────────────────
        tools: list[dict] = []
        web_search = getattr(bot, "web_search", None)
        if web_search and web_search.available and not await web_search.is_quota_exceeded():
            tools.extend(web_search.get_tool_definitions())
        apex_api = getattr(bot, "apex_api", None)
        if apex_api and apex_api.available:
            tools.append(apex_api.get_tool_definition())

        async def _tool_executor(name: str, arguments: str) -> str:
            args = json.loads(arguments)
            if name in ("web_search", "image_search"):
                if name == "image_search":
                    return await web_search.search_images(args["query"])
                return await web_search.search(args["query"])
            if name == "apex_legends":
                return await apex_api.execute(
                    args.get("action", ""),
                    player_name=args.get("player_name", ""),
                    platform=args.get("platform", "PC"),
                )
            return f"Unknown tool: {name}"

        if tools:
            reply, _ = await bot.openai.complete_with_tools(
                system_prompt, openai_messages, tools, _tool_executor,
                purpose="twitch_response",
                user_id=f"twitch:{author}",
            )
        else:
            reply = await bot.openai.complete(
                system_prompt, openai_messages,
                purpose="twitch_response",
                user_id=f"twitch:{author}",
            )

        if len(reply) > 480:
            reply = reply[:477] + "..."

        if channel_name in bot._channel_ids:
            # Chaîne invitée : envoi via IRC (pas d'autorisation broadcaster requise)
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(reply)
            else:
                logger.warning("IRC non connecté pour {ch}, réponse ignorée", ch=channel_name)
        else:
            # Chaîne home : envoi via Helix API
            await bot.twitch_api.send_message(text=reply)
        bot.set_cooldown(user_id)

        if getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_twitch_response(channel_id)

        bot.memory.append_message(channel_id, author, content, platform="twitch")
        bot.memory.append_message(channel_id, "Wally", reply, platform="twitch")

        _fire(_post_process(bot, content, platform, user_id, trust, context_msgs, channel_id=channel_id))

    except Exception as e:
        logger.error("Twitch message handling error: {e}", e=e)


async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
    trust: float,
    context_messages: list[dict] | None = None,
    channel_id: str = "",
) -> None:
    try:
        await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
        )
        insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
        if any(w in text.lower() for w in insult_words):
            await bot.db.update_trust_score(platform, user_id, -0.05)
        else:
            await bot.db.update_trust_score(platform, user_id, 0.01)
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)
