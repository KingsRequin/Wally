"""Cerveau vocal : branchement gate + génération de la réponse parlée."""
from loguru import logger

_VOICE_TARGET_NOTICE = (
    "Tu participes à une conversation VOCALE. Réponds en une à deux phrases courtes, "
    "naturelles à l'oral, sans formatage ni emoji. Réponds UNIQUEMENT avec ton propre texte."
)


async def generate_voice_reply(
    bot,
    speaker_label: str,
    transcript: str,
    history: list[dict],
    tools: list[dict],
    tool_executor,
    speaker_user_id: str = "",
) -> str:
    """Assemble system_prompt (persona+émotions) + messages, appelle complete_with_tools.

    Signature finale (pour Task 5) :
        generate_voice_reply(bot, speaker_label, transcript, history,
                             tools, tool_executor, speaker_user_id="")

    `speaker_user_id` est le raw Discord snowflake (sans préfixe "discord:").
    Task 6 popule `service.voice_tools` et `service.tool_executor` — laisser None
    jusqu'alors est sûr, complete_with_tools accepte tools=[] et tool_executor=None.
    """
    emotion_state = bot.emotion.get_state()

    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id=speaker_user_id, query=transcript, limit=3
        )
    except Exception as e:
        logger.warning("voice memory.search a échoué: {e}", e=e)
        memory_context = ""

    system_prompt = bot.prompts.build_voice_system(
        emotion_state=emotion_state,
        memory_context=memory_context or "",
        speaker_label=speaker_label,
        persona_block=bot.persona.build_prompt_block(),
        emotion_directives=bot.persona.emotion_directives,
        weekday_directives=bot.persona.weekday_directives,
        composite_directives=bot.persona.composite_directives,
        secondary_directives=bot.persona.secondary_directives,
        active_secondaries=bot.emotion.get_secondary_emotions(),
    )
    system_prompt = f"{system_prompt}\n\n{_VOICE_TARGET_NOTICE}"

    messages = list(history)
    messages.append({"role": "user", "content": f"{speaker_label}: {transcript}"})

    reply, _tools_called = await bot.llm.complete_with_tools(
        system_prompt, messages, tools, tool_executor,
        purpose="discord_voice",
    )
    return reply or ""


async def handle_transcript(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str
) -> None:
    """Transcrit → gate → (si RESPOND) génère et fait parler Wally."""
    transcript = (transcript or "").strip()
    if not transcript:
        return

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_activity(
                channel_id=service.channel_id, author=speaker_label, content=transcript
            )
    except Exception as e:
        logger.warning("voice notify_activity a échoué: {e}", e=e)

    gate = getattr(bot, "response_gate", None)
    decision = "RESPOND"
    if gate is not None:
        try:
            gd = await gate.decide(
                message_content=transcript,
                author_user_id=speaker_user_id,
                emotion_state=bot.emotion.get_state(),
                relationship_facts=[],
                active_desires=[],
                is_triggered=True,
            )
            decision = gd.decision
        except Exception as e:
            logger.warning("voice gate.decide a échoué, fallback RESPOND: {e}", e=e)

    if decision != "RESPOND":
        logger.info("voice: gate={d}, Wally ne parle pas", d=decision)
        return

    # voice_tools et tool_executor définis en Task 6 (join/leave) ; vide/None en attendant.
    # complete_with_tools accepte tools=[] et tool_executor=None sans crash.
    tools = getattr(service, "voice_tools", [])
    tool_executor = getattr(service, "tool_executor", None)

    try:
        text = await generate_voice_reply(
            bot=bot,
            speaker_label=speaker_label,
            transcript=transcript,
            history=list(service.history),
            tools=tools,
            tool_executor=tool_executor,
            speaker_user_id=speaker_user_id,
        )
    except Exception as e:
        logger.error("voice generate_voice_reply a échoué: {e}", e=e)
        return

    if not text:
        return

    # Fix 3 : appel speak() AVANT d'écrire dans service.history pour éviter
    # un état incohérent si speak() lève une exception.
    await service.speak(text)

    service.history.append({"role": "user", "content": f"{speaker_label}: {transcript}"})
    service.history.append({"role": "assistant", "content": text})
    service.history[:] = service.history[-12:]  # fenêtre courte

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(service.channel_id, content=text)
    except Exception as e:
        logger.warning("voice notify_reply a échoué: {e}", e=e)
