# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

from bot.core.emotion import build_emotion_tag

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
    channel_name: str = payload.broadcaster.name
    channel_id = f"twitch:{channel_name}"

    # Capture passive : prelude AVANT d'ajouter le message courant
    prelude = bot.memory.get_prelude(channel_id)
    bot.memory.append_prelude(channel_id, author, content)

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

        mem_context = await bot.memory.search(platform, user_id, content)
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
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)
        user_content = prelude_block + context_block + f"\n[{author}]: {content}"

        reply = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_response",
        )

        if len(reply) > 480:
            reply = reply[:477] + "..."

        await bot.twitch_api.send_message(text=reply)
        bot.set_cooldown(user_id)

        bot.memory.append_message(channel_id, author, content)
        bot.memory.append_message(channel_id, "Wally", reply)

        tag = build_emotion_tag(bot.emotion.get_state())
        _fire(bot.memory.add(platform, user_id, content, emotion_context=tag))
        _fire(_post_process(bot, content, platform, user_id, trust, context_msgs))

    except Exception as e:
        logger.error("Twitch message handling error: {e}", e=e)


async def _post_process(
    bot: "WallyTwitch",
    text: str,
    platform: str,
    user_id: str,
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
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)
