"""Cerveau vocal : branchement gate + génération de la réponse parlée."""
from loguru import logger

_VOICE_TARGET_NOTICE = (
    "Tu participes à une conversation VOCALE. Réponds en une à deux phrases courtes, "
    "naturelles à l'oral, sans formatage ni emoji. Réponds UNIQUEMENT avec ton propre texte."
)


async def generate_voice_reply(
    bot, speaker_label: str, transcript: str, history: list[dict],
    tools: list[dict], tool_executor
) -> str:
    """Assemble system_prompt (persona+émotions) + messages, appelle complete_with_tools."""
    emotion_state = bot.emotion.get_state()

    # Le brief passait user_id=None — INCORRECT : search() exige un user_id non-None.
    # On extrait l'id depuis le label si nécessaire, mais ici on reçoit speaker_user_id
    # via handle_transcript → on le stocke sur le service ou on l'ignore avec "".
    # Ici generate_voice_reply ne reçoit pas speaker_user_id directement ; on passe ""
    # (chaîne vide) pour éviter un crash — la recherche renverra "" en cas d'échec.
    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id="", query=transcript, limit=3
        )
    except Exception as e:
        logger.warning("voice memory.search a échoué: {e}", e=e)
        memory_context = ""

    system_prompt = bot.prompts.build_voice_system(
        emotion_state=emotion_state,
        memory_context=memory_context or "",
        speaker_label=speaker_label,
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

    # voice_tools défini en Task 6 (join/leave) ; vide en attendant
    tools = getattr(service, "voice_tools", [])
    tool_executor = getattr(service, "tool_executor", None)

    # Recherche mémoire avec le vrai user_id du locuteur
    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id=speaker_user_id, query=transcript, limit=3
        )
    except Exception as e:
        logger.warning("voice memory.search a échoué: {e}", e=e)
        memory_context = ""

    emotion_state = bot.emotion.get_state()
    system_prompt = bot.prompts.build_voice_system(
        emotion_state=emotion_state,
        memory_context=memory_context or "",
        speaker_label=speaker_label,
    )
    system_prompt = f"{system_prompt}\n\n{_VOICE_TARGET_NOTICE}"

    messages = list(service.history)
    messages.append({"role": "user", "content": f"{speaker_label}: {transcript}"})

    try:
        reply, _tools_called = await bot.llm.complete_with_tools(
            system_prompt, messages, tools, tool_executor,
            purpose="discord_voice",
        )
    except Exception as e:
        logger.error("voice complete_with_tools a échoué: {e}", e=e)
        return

    text = reply or ""
    if not text:
        return

    service.history.append({"role": "user", "content": f"{speaker_label}: {transcript}"})
    service.history.append({"role": "assistant", "content": text})
    service.history[:] = service.history[-12:]  # fenêtre courte

    await service.speak(text)

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(service.channel_id, content=text)
    except Exception as e:
        logger.warning("voice notify_reply a échoué: {e}", e=e)
