# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import TYPE_CHECKING

from loguru import logger

from bot.discord.handlers import _check_spontaneous_trigger, _parse_react_tag

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()
_spontaneous_cooldowns: dict[str, float] = {}


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
    if getattr(bot, "fact_extractor", None) is not None:
        bot.fact_extractor.record_message(channel_id, "twitch", user_id, author, content, is_reply=False)

    # Reaction tracking: scan for positive reactions in Twitch window
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker:
        tracker.check_twitch_message(channel_id, content)

    # Spontaneous intervention (Twitch)
    if bot.config.bot.spontaneous_twitch_enabled:
        import time as _time
        state = bot.emotion.get_state()
        trigger_type = _check_spontaneous_trigger(
            content,
            curiosity=state.get("curiosity", 0.0),
            anger=state.get("anger", 0.0),
            boredom=state.get("boredom", 0.0),
        )
        if trigger_type:
            now = _time.time()
            cooldown = bot.config.bot.spontaneous_cooldown_seconds
            if now - _spontaneous_cooldowns.get(channel_id, 0) >= cooldown:
                prob = (
                    bot.config.bot.spontaneous_passion_probability
                    if trigger_type == "passion"
                    else bot.config.bot.spontaneous_probability
                )
                if random.random() < prob:
                    _spontaneous_cooldowns[channel_id] = now
                    _fire(_spontaneous_respond_twitch(bot, channel_name, channel_id, author, content))

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

        # Inject trust + love levels into memory context
        love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
        trust_line = f"\nNiveau de confiance : {trust:.2f}/1.0"
        love_line = f"\nNiveau d'affection : {love:.2f}/1.0"
        if mem_context:
            mem_context = mem_context + trust_line + love_line
        else:
            mem_context = (trust_line + love_line).strip()

        # Inject recent successful jokes for this channel
        try:
            recent_jokes = await bot.db.get_recent_jokes(channel_id, limit=3)
            if recent_jokes:
                jokes_block = "\n--- Tes blagues récentes qui ont bien marché dans ce salon ---"
                for j in recent_jokes:
                    jokes_block += f'\n- "{j}"'
                mem_context = (mem_context + jokes_block) if mem_context else jokes_block.strip()
        except Exception:
            pass

        # Inject community opinions
        try:
            opinions = await bot.db.get_opinions(limit=10)
            if opinions:
                opinions_block = "\n--- Tes opinions sur les sujets de la communauté ---"
                for o in opinions:
                    opinions_block += f'\n- {o["topic"]} : "{o["opinion"]}"'
                mem_context = (mem_context + opinions_block) if mem_context else opinions_block.strip()
        except Exception:
            pass

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

        # Strip [react:] tag (no emoji reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)

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
            bot.reaction_tracker.track_twitch_response(channel_id, reply_text=reply)

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
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
        )

        if llm_deltas:
            await bot.db.update_trust_score(platform, user_id, llm_deltas["trust_delta"])
            if llm_deltas["love_delta"] > 0:
                await bot.db.update_love_score(
                    platform, user_id, llm_deltas["love_delta"],
                    bot.config.bot.love_decay_lambda,
                )
        else:
            # Fallback: simple heuristic when LLM unavailable
            insult_words = ["idiot", "stupide", "nul", "merde", "shut up", "stfu"]
            if any(w in text.lower() for w in insult_words):
                await bot.db.update_trust_score(platform, user_id, -0.05)
            else:
                await bot.db.update_trust_score(platform, user_id, 0.01)

        if llm_deltas and llm_deltas.get("user_facts"):
            await bot.memory.add(platform, user_id, "\n".join(llm_deltas["user_facts"]))
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)


async def _spontaneous_respond_twitch(
    bot: "WallyTwitch", channel_name: str, channel_id: str,
    author: str, content: str,
) -> None:
    """Generate and send a spontaneous Twitch response."""
    try:
        prelude = bot.memory.get_prelude(channel_id)
        situation = {"platform": "Twitch", "streamer": channel_name, "channel": f"#{channel_name}"}
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + prelude_block
            + f"\n[{author}]: {content}"
        )
        reply = await bot.openai.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_spontaneous",
        )
        # Strip react tag (no reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)
        if len(reply) > 480:
            reply = reply[:477] + "..."

        if channel_name in bot._channel_ids:
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(reply)
        else:
            await bot.twitch_api.send_message(text=reply)

        bot.memory.append_message(channel_id, "Wally", reply, platform="twitch")
        logger.info("Spontaneous intervention in twitch:{ch}", ch=channel_name)

    except Exception as e:
        logger.error("Twitch spontaneous error: {e}", e=e)
