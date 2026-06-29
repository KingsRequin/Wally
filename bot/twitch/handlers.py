# bot/twitch/handlers.py
from __future__ import annotations

import asyncio
import difflib
import json
import os
import random
import re
import time
from typing import TYPE_CHECKING

from loguru import logger

from bot.intelligence.prompts import assemble_memory_context, build_session_recall_block
from bot.core.conversation_log import new_trace_id
from bot.discord.handlers import _check_spontaneous_trigger, _parse_react_tag, _NOTE_TOOLS, _third_party_mention_context

if TYPE_CHECKING:
    from bot.twitch.bot import WallyTwitch

from bot.twitch.commands import dispatch_command


def _resolve_twitch_roles(badges: list) -> list[str]:
    """Map Twitch badges to the action permission hierarchy."""
    roles = ["everyone"]
    badge_names = {b.id if hasattr(b, 'id') else str(b) for b in badges}
    if "subscriber" in badge_names:
        roles.append("subscriber")
    if "vip" in badge_names:
        roles.append("vip")
    if "moderator" in badge_names:
        roles.append("moderator")
    if "broadcaster" in badge_names:
        roles.append("admin")
    return roles

# Strong references to fire-and-forget tasks to prevent GC cancellation.
_bg_tasks: set[asyncio.Task] = set()
_spontaneous_cooldowns: dict[str, float] = {}


def _fire(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


def _build_situation(bot: "WallyTwitch", channel_name: str) -> dict:
    """Build situation dict with stream info if available."""
    situation: dict = {
        "platform": "Twitch",
        "streamer": channel_name,
        "channel": f"#{channel_name}",
    }
    stream = bot._stream_info
    if stream.get("live"):
        situation["stream_live"] = True
        situation["stream_category"] = stream.get("category")
        situation["stream_title"] = stream.get("title")
        situation["stream_viewers"] = stream.get("viewers", 0)
    return situation


def _clog(bot: "WallyTwitch", channel: str, event_type: str, **fields) -> None:
    """Journalise un événement de conversation Twitch (no-op si logger absent)."""
    clog = getattr(bot, "conv_log", None)
    if clog is not None:
        clog.log("twitch", channel, event_type, **fields)


async def handle_message(bot: "WallyTwitch", payload) -> None:
    """Handle an incoming channel.chat.message EventSub payload."""
    # Dashboard message counter (tous les messages, pas seulement les triggers)
    if getattr(bot, "dashboard_state", None) is not None:
        bot.dashboard_state.message_count += 1
        bot.dashboard_state.message_count_twitch += 1

    content: str = payload.message.text
    content_lower = content.lower()
    author: str = payload.chatter.name
    user_id: str = str(payload.chatter.id)
    # Normalisé en minuscules — cohérent avec les clés de _channel_ids
    channel_name: str = payload.broadcaster.name.lower()
    channel_id = f"twitch:{channel_name}"

    # Incrémentation du compteur de messages pour les visites actives
    active_visits = getattr(bot, "_active_visits", {})
    if channel_name in active_visits:
        active_visits[channel_name]["msg_count"] += 1

    # Dispatch commandes ! (overlay, !mood, !code, …)
    if await dispatch_command(bot, payload, content, author, channel_name):
        return

    # Marquer la chaîne invitée comme "vue live" dès réception d'un message
    if channel_name in bot._channel_ids:
        bot._channel_was_live[channel_name] = True

    # Ignorer les propres messages de Wally qui reviennent via EventSub
    bot_id = str(getattr(bot.twitch_api, "_bot_id", ""))
    if bot_id and user_id == bot_id:
        return

    # Ignorer les bots Twitch connus (username ou badge "bot")
    _KNOWN_BOTS: frozenset[str] = frozenset({
        "nightbot", "streamlabs", "streamelements", "moobot", "fossabot",
        "wizebot", "supibot", "botrixoficial", "sery_bot", "electricallongboard",
        "streamlabsbot", "commanderroot", "soundalerts", "elbierro", "tangiabot",
        "kofistreambot", "own3d", "streamelementsbot",
    })
    if author.lower() in _KNOWN_BOTS:
        return
    badges = getattr(payload, "badges", []) or []
    badge_ids = {b.id if hasattr(b, "id") else str(b) for b in badges}
    if "bot" in badge_ids:
        return

    # Persiste le login Twitch pour que le dashboard affiche un nom lisible
    await bot.db.upsert_memory_user(f"twitch:{user_id}", "twitch", username=author)

    # Capture passive : prelude AVANT d'ajouter le message courant
    prelude = bot.memory.get_prelude(channel_id)
    bot.memory.append_prelude(channel_id, author, content)
    if getattr(bot, "cognitive_loop", None) is not None:
        try:
            # « Pertinent » = le message vise Wally (mention @nick ou nom déclencheur)
            # → cadence cognitive vive ; sinon perception passive (Phase 2c).
            _tb_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
            _relevant = bool(_tb_nick and f"@{_tb_nick}" in content_lower) or any(
                n.lower() in content_lower for n in bot.config.bot.trigger_names
            )
            bot.cognitive_loop.notify_activity(
                channel_id=channel_id,
                author=author,
                content=content,
                relevant=_relevant,
                user_key=f"twitch:{user_id}",
            )
        except Exception:
            pass
    if getattr(bot, "fact_extractor", None) is not None:
        bot.fact_extractor.record_message(channel_id, "twitch", user_id, author, content, is_reply=False,
                                          origin=f"Twitch/{channel_name}")

    # Reaction tracking: scan for positive reactions in Twitch window
    tracker = getattr(bot, "reaction_tracker", None)
    if tracker:
        tracker.check_twitch_message(channel_id, content)

    _trace = getattr(payload, "message_id", None) or new_trace_id("twitch")
    _clog(
        bot, channel_name, "message_in",
        trace_id=_trace, author=author, author_id=user_id, content=content,
    )

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
        now = _time.time()
        cooldown = bot.config.bot.spontaneous_cooldown_seconds
        cooldown_ok = now - _spontaneous_cooldowns.get(channel_id, 0) >= cooldown

        if trigger_type and cooldown_ok:
            prob = (
                bot.config.bot.spontaneous_passion_probability
                if trigger_type == "passion"
                else bot.config.bot.spontaneous_probability
            )
            if random.random() < prob:
                _spontaneous_cooldowns[channel_id] = now
                _clog(
                    bot, channel_name, "gate_decision",
                    trace_id=_trace, triggered=False, spontaneous=True,
                    trigger_type=trigger_type, decision="spontaneous",
                )
                _fire(_spontaneous_respond_twitch(bot, channel_name, channel_id, author, content, prelude_snapshot=prelude))
        elif not trigger_type and cooldown_ok:
            pass

    # Trigger check
    bot_nick = os.getenv("TWITCH_BOT_NICK", "").lower()
    triggered = (bot_nick and f"@{bot_nick}" in content_lower) or any(
        name.lower() in content_lower for name in bot.config.bot.trigger_names
    )
    if not triggered:
        return

    if bot.is_on_cooldown(user_id):
        return

    _clog(bot, channel_name, "gate_decision", trace_id=_trace, triggered=True, decision="respond")

    try:
        self_name = bot.config.bot.name
        platform = "twitch"
        trust = await bot.db.get_trust_score(platform, user_id)

        mem_context = await bot.memory.search(platform, user_id, content, context_messages=prelude, username_hint=author)

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

        # ── Fetch context messages early (needed for priority 6) ──────
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        # ── Assemble memory context with token budget ──────────────────
        max_tokens = bot.config.bot.memory_context_max_tokens
        memory_parts: list[tuple[int, str]] = []

        # Priority 1: Semantic memories (already fetched)
        if mem_context:
            memory_parts.append((1, mem_context))

        # Priority 2: Résumés de sessions précédentes (cross-session recall)
        try:
            summaries = await bot.db.get_recent_session_summaries(platform, channel_id, limit=3)
            recall_block = build_session_recall_block(summaries)
            if recall_block:
                memory_parts.append((2, recall_block))
        except Exception:
            pass

        # Priority 4: Recent successful jokes for this channel
        try:
            recent_jokes = await bot.db.get_recent_jokes(channel_id, limit=3)
            if recent_jokes:
                jokes_block = "--- Tes blagues récentes qui ont bien marché dans ce salon ---"
                for j in recent_jokes:
                    jokes_block += f'\n- "{j}"'
                memory_parts.append((4, jokes_block))
        except Exception:
            pass

        # Priority 5: Community topics (sujets de communauté enrichis)
        try:
            topics = await bot.db.get_topics(limit=5)
            if topics:
                topics_block = "--- Sujets de la communauté ---"
                for t in topics:
                    names = ", ".join(p["name"] for p in t["participants"]) if t["participants"] else ""
                    who = f" — {names} en parlent" if names else ""
                    topics_block += f'\n- {t["name"]}{who} — ton avis : "{t["opinion"]}"'
                memory_parts.append((5, topics_block))
        except Exception:
            pass

        # Priority 6: Third-party mentions
        try:
            third_party_ctx = await _third_party_mention_context(
                bot, platform, user_id, prelude, context_msgs
            )
            if third_party_ctx:
                memory_parts.append((6, third_party_ctx))
        except Exception:
            pass

        mem_context = assemble_memory_context(memory_parts, max_tokens)

        # Trust/love go in separate relationship_context (outside token budget)
        love = await bot.db.get_love_score(platform, user_id, bot.config.bot.love_decay_lambda)
        relationship_context = f"Niveau de confiance : {trust:.2f}/1.0\nNiveau d'affection : {love:.2f}/1.0"

        # Portrait de la personne (user model) — non-fatal
        person_context = ""
        try:
            person_context = await bot.db.get_user_profile(f"{platform}:{user_id}") or ""
        except Exception:
            pass

        # Persistent notes
        try:
            persistent_notes = await bot.db.get_persistent_notes()
        except Exception:
            persistent_notes = []

        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=mem_context,
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            relationship_context=relationship_context,
            person_context=person_context,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
            persistent_notes=persistent_notes or None,
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)
        target_notice = (
            f"\n⚠️ Tu réponds à **{author}**. "
            "Le contexte ci-dessus contient des messages de PLUSIEURS personnes — "
            "attribue chaque propos à son auteur (indiqué entre crochets). "
            "Ne confonds JAMAIS les propos d'un utilisateur avec ceux d'un autre. "
            "Réponds UNIQUEMENT avec ton propre texte — ne répète jamais le message auquel tu réponds. "
            "Sois BREF : 1 à 2 phrases maximum, comme dans un vrai chat Twitch."
        )
        user_content = prelude_block + context_block + target_notice + f"\n[{author}]: {content}"

        openai_messages = [{"role": "user", "content": user_content}]

        # ── Collect available tools ──────────────────────────────────────
        tools: list[dict] = []
        web_search = getattr(bot, "web_search", None)
        if web_search and web_search.available and not await web_search.is_quota_exceeded():
            tools.extend(web_search.get_tool_definitions())
        scrape = getattr(bot, "scrape", None)
        if scrape and scrape.available and not await scrape.daily_limit_reached():
            tools.extend(scrape.get_tool_definitions())
        apex_api = getattr(bot, "apex_api", None)
        if apex_api and apex_api.available:
            tools.append(apex_api.get_tool_definition())
        action_service = getattr(bot, "action_service", None)
        if action_service:
            tools.extend(action_service.get_tool_definitions())
        tools.extend(_NOTE_TOOLS)

        async def _tool_executor_impl(name: str, arguments: str) -> str:
            _clog(bot, channel_name, "tool_called", trace_id=_trace, tool=name, args=arguments)
            args = json.loads(arguments)
            if name == "save_persistent_note":
                await bot.db.upsert_persistent_note(args["title"], args["content"])
                return json.dumps({"status": "ok", "message": f"Note '{args['title']}' sauvegardée."})
            if name == "delete_persistent_note":
                deleted = await bot.db.delete_persistent_note(args["title"])
                if deleted:
                    return json.dumps({"status": "ok", "message": f"Note '{args['title']}' supprimée."})
                return json.dumps({"status": "not_found", "message": f"Note '{args['title']}' introuvable."})
            if name == "save_user_memory":
                await bot.memory.add("twitch", user_id, args["content"], username=author,
                                     origin=f"Twitch/{channel_name}")
                return json.dumps({"status": "ok", "message": "Souvenir sauvegardé."})
            if name in ("web_search", "image_search"):
                if name == "image_search":
                    return await web_search.search_images(args["query"])
                return await web_search.search(args["query"], platform="twitch")
            if name == "scrape_url":
                return await scrape.scrape(args["url"])
            if name == "apex_legends":
                return await apex_api.execute(
                    args.get("action", ""),
                    player_name=args.get("player_name", ""),
                    platform=args.get("platform", "PC"),
                )
            if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
                badges = getattr(payload, "badges", []) or []
                user_roles = _resolve_twitch_roles(badges)
                result = await action_service.execute_tool(
                    name, args,
                    user_id=str(payload.chatter.id),
                    platform="twitch",
                    user_roles=user_roles,
                    channel_id=channel_name,
                )
                return json.dumps(result)
            return f"Unknown tool: {name}"

        async def _tool_executor(name: str, arguments: str) -> str:
            result = await _tool_executor_impl(name, arguments)
            _clog(bot, channel_name, "tool_result", trace_id=_trace, tool=name, result=str(result)[:500])
            return result

        _llm_t0 = time.monotonic()
        if tools:
            reply, _tools_called = await bot.llm.complete_with_tools(
                system_prompt, openai_messages, tools, _tool_executor,
                purpose="twitch_response",
                user_id=f"twitch:{author}",
            )
        else:
            reply = await bot.llm.complete(
                system_prompt, openai_messages,
                purpose="twitch_response",
                user_id=f"twitch:{author}",
            )
            _tools_called = []

        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, channel_name, "llm_call",
            trace_id=_trace,
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            tools_offered=[t.get("function", {}).get("name") for t in tools],
            tools_called=_tools_called,
            latency_ms=int((time.monotonic() - _llm_t0) * 1000),
            system_prompt=system_prompt,
            user_content=user_content,
            raw_reply=reply,
        )

        # Strip [react:] tag (no emoji reactions on Twitch)
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)

        if len(reply) > 480:
            reply = reply[:477] + "..."

        if channel_name in bot._channel_ids:
            # Chaîne invitée : envoi via IRC — mention @author pour simuler une réponse
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(f"@{author} {reply}")
            else:
                logger.warning("IRC non connecté pour {ch}, réponse ignorée", ch=channel_name)
        else:
            # Chaîne home : envoi via Helix API avec reply thread
            msg_id = getattr(payload, "message_id", None) or None
            await bot.twitch_api.send_message(
                text=reply,
                reply_parent_message_id=msg_id,
            )
        bot.set_cooldown(user_id)
        _clog(
            bot, channel_name, "message_out",
            trace_id=_trace, author=self_name, content=reply, parts=1,
            send_mode="irc" if channel_name in bot._channel_ids else "helix",
        )
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(channel_id, content=reply)

        if getattr(bot, "reaction_tracker", None):
            bot.reaction_tracker.track_twitch_response(channel_id, reply_text=reply)

        bot.memory.append_message(channel_id, author, content, platform="twitch")
        bot.memory.append_prelude(channel_id, self_name, reply)
        bot.memory.append_message(channel_id, self_name, reply, platform="twitch")

        _fire(_post_process(bot, content, platform, user_id, trust, context_msgs, channel_id=channel_id, username=author, trace_id=_trace, conv_channel=channel_name))

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
    username: str = "",
    trace_id: str = "",
    conv_channel: str = "",
) -> None:
    try:
        _emo_before = bot.emotion.get_state()
        llm_deltas = await bot.emotion.process_message(
            text, trust_score=trust, context_messages=context_messages,
            trigger_user=user_id, channel_id=channel_id, platform="twitch",
            user_id=user_id,
        )
        _emo_after = bot.emotion.get_state()
        if trace_id:
            _deltas = {
                k: round(_emo_after.get(k, 0.0) - _emo_before.get(k, 0.0), 3)
                for k in ("anger", "joy", "sadness", "curiosity", "boredom")
            }
            if any(v != 0 for v in _deltas.values()):
                _clog(
                    bot, conv_channel, "emotion_change",
                    trace_id=trace_id,
                    deltas=_deltas,
                    after={k: round(_emo_after.get(k, 0.0), 3) for k in ("anger", "joy", "sadness", "curiosity", "boredom")},
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
            await bot.memory.add(platform, user_id, "\n".join(llm_deltas["user_facts"]), username=username,
                                 origin=f"Twitch/{conv_channel}" if conv_channel else None)
        if trace_id:
            _clog(
                bot, conv_channel, "post_process",
                trace_id=trace_id,
                facts_extracted=len(llm_deltas.get("user_facts", [])) if llm_deltas else 0,
            )
    except Exception as e:
        logger.error("Twitch post-process error: {e}", e=e)


async def _announce_overlay_image(
    bot: "WallyTwitch", channel_name: str, channel_id: str, image: dict,
    dashboard_state, overlay_payload: dict,
) -> None:
    """Generate LLM message first, then send overlay image + chat message simultaneously."""
    try:
        self_name = bot.config.bot.name
        title = image.get("title") or "sans titre"
        creator = image.get("username") or "quelqu'un"
        prompt_text = image.get("prompt") or ""

        prelude = bot.memory.get_prelude(channel_id)
        context_msgs = await bot.memory.get_context_summarized_if_needed(channel_id)

        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        context_block = bot.prompts.build_context_block(context_msgs)

        image_desc = f"Image affichée sur le stream : \"{title}\" par {creator}."
        if prompt_text:
            image_desc += f" Prompt original : \"{prompt_text}\""

        user_content = (
            "[CONTEXTE: Quelqu'un vient de déclencher !image sur le stream. "
            "Une image de la galerie s'affiche sur l'overlay. "
            "Présente cette image au chat en UNE phrase courte et naturelle. "
            "Mentionne le créateur de l'image.]\n\n"
            + prelude_block
            + context_block
            + f"\n[SYSTÈME]: {image_desc}"
        )

        # 1. Générer le message LLM (le plus lent)
        reply = await bot.llm.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_overlay_announce",
        )

        # Strip react tag
        if reply.startswith("[react:"):
            import re as _re
            reply = _re.sub(r"^\[react:.+?\]\s*", "", reply)
        if len(reply) > 480:
            reply = reply[:477] + "..."

        # 2. Envoyer overlay + message chat en même temps
        try:
            dashboard_state.overlay_image_queue.put_nowait(overlay_payload)
        except asyncio.QueueFull:
            pass

        if channel_name in bot._channel_ids:
            irc_channel = bot.get_channel(channel_name)
            if irc_channel:
                await irc_channel.send(reply)
        else:
            await bot.twitch_api.send_message(text=reply)

        bot.memory.append_prelude(channel_id, self_name, reply)
        bot.memory.append_message(channel_id, self_name, reply, platform="twitch")
    except Exception as e:
        logger.error("Overlay image announce error: {e}", e=e)


async def _spontaneous_respond_twitch(
    bot: "WallyTwitch", channel_name: str, channel_id: str,
    author: str, content: str,
    recall_memory: str | None = None,
    prelude_snapshot: list[dict] | None = None,
) -> None:
    """Generate and send a spontaneous Twitch response."""
    try:
        self_name = bot.config.bot.name
        prelude = prelude_snapshot if prelude_snapshot is not None else bot.memory.get_prelude(channel_id)
        situation = _build_situation(bot, channel_name)
        system_prompt = bot.prompts.build_system_prompt(
            emotion_state=bot.emotion.get_state(),
            memory_context=recall_memory or "",
            situation=situation,
            persona_block=bot.persona.build_prompt_block(),
            emotion_directives=bot.persona.emotion_directives,
            weekday_directives=bot.persona.weekday_directives,
            composite_directives=bot.persona.composite_directives,
            secondary_directives=bot.persona.secondary_directives,
            active_secondaries=bot.emotion.get_secondary_emotions(),
        )
        prelude_block = bot.prompts.build_prelude_block(prelude)
        recall_block = ""
        if recall_memory:
            recall_block = (
                "\n--- Souvenir qui te revient ---\n"
                f"{recall_memory}\n"
                f"Tu viens de te rappeler quelque chose en lien avec ce que dit "
                f"{author}. Évoque-le naturellement.\n\n"
            )
            logger.info("Memory recall for {user} on Twitch: {mem}", user=author, mem=recall_memory[:80])
        user_content = (
            "[CONTEXTE: Tu n'as PAS été mentionné. Tu interviens spontanément "
            "parce que le sujet t'intéresse ou te fait réagir. Réponds en une "
            "phrase courte et percutante, comme un commentaire lâché en passant.]\n\n"
            + recall_block
            + prelude_block
            + f"\n[{author}]: {content}"
        )
        reply = await bot.llm.complete(
            system_prompt,
            [{"role": "user", "content": user_content}],
            purpose="twitch_spontaneous",
        )
        _spont_trace = new_trace_id("twitch_spont")
        _emo = bot.emotion.get_state()
        _dom = max(_emo, key=_emo.get) if _emo else None
        _clog(
            bot, channel_name, "llm_call",
            trace_id=_spont_trace, kind="spontaneous",
            model=getattr(bot.llm, "_model", "?"),
            dominant_emotion=_dom,
            emotion_value=round(_emo.get(_dom, 0.0), 3) if _dom else None,
            system_prompt=system_prompt, user_content=user_content, raw_reply=reply,
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
        _clog(
            bot, channel_name, "message_out",
            trace_id=_spont_trace, kind="spontaneous", author=self_name,
            content=reply, parts=1,
        )
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(channel_id, content=reply)

        bot.memory.append_prelude(channel_id, self_name, reply)
        bot.memory.append_message(channel_id, self_name, reply, platform="twitch")
        logger.info("Spontaneous intervention in twitch:{ch}", ch=channel_name)

    except Exception as e:
        logger.error("Twitch spontaneous error: {e}", e=e)
