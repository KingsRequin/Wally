"""Cerveau vocal : branchement gate + génération de la réponse parlée."""
import re
from difflib import SequenceMatcher

from loguru import logger

_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)


_LEAVE_RE = re.compile(
    r"(quitte\w*\s+(le\s+)?(voc|vocal|salon|chan)"
    r"|d[ée]connecte"
    r"|d[ée]gage"
    r"|va[\s-]?t'?[\s-]?en"
    r"|casse[\s-]?toi"
    r"|barre[\s-]?toi"
    r"|fous[\s-]?(le[\s-]?)?camp"
    r"|tu peux (partir|y aller|t'en aller|nous laisser|d[ée]gager|t'en go)"
    r"|sors\s+du\s+(voc|vocal|salon)"
    r"|laisse[\s-]?nous"
    r"|tu d[ée]gages"
    r"|d[ée]go?\s+du\s+(voc|vocal))",
    re.IGNORECASE,
)


def _is_leave_request(transcript: str) -> bool:
    """Vrai si la parole exprime une demande explicite de quitter le vocal."""
    return bool(_LEAVE_RE.search(transcript or ""))


def _is_named(transcript: str, trigger_names: list[str]) -> bool:
    """Vrai si Wally est nommé — tolère les déformations du STT (wallyd, wallie, wali…)."""
    low = transcript.lower()
    words = _WORD_RE.findall(low)
    for trig in trigger_names:
        t = str(trig).lower().strip()
        if not t:
            continue
        if t in low:  # correspondance exacte (substring)
            return True
        for w in words:  # correspondance approchée mot à mot
            if SequenceMatcher(None, w, t).ratio() >= 0.72:
                return True
    return False

_VOICE_TARGET_NOTICE = (
    "CONTEXTE : tu es actuellement connecté dans un salon VOCAL Discord et tu parles à voix "
    "haute. Tu ENTENDS les gens parler (transcription) et tu leur réponds ORALEMENT — ce n'est "
    "pas du texte écrit. C'est une conversation de GROUPE : plusieurs personnes peuvent parler, "
    "et tu en fais partie comme un participant parmi les autres. Dans l'historique, chaque réplique "
    "est préfixée par le nom de la personne qui parle (ex 'Alex: ...'). Suis le fil GLOBAL de la "
    "discussion, tiens compte de ce que se disent les gens entre eux, et interviens naturellement — "
    "tu n'as pas à répondre à chaque phrase ni à chaque personne séparément. "
    "Réponds en une à deux phrases courtes, naturelles à l'oral, sans "
    "formatage, sans markdown, sans emoji. Réponds UNIQUEMENT avec ton propre texte.\n"
    "TON DE VOIX : par défaut ta voix suit ton humeur. Tu peux choisir un ton précis UNIQUEMENT "
    "en plaçant UN SEUL mot-tag entre crochets au TOUT DÉBUT de ta phrase, parmi exactement : "
    "[murmure], [crie], [doux], [joyeux], [triste], [énervé], [excité], [surpris]. "
    "Exemple correct : '[murmure] approche, j'ai un secret'. "
    "RÈGLES STRICTES sur les crochets : un seul mot-tag, au tout début, rien d'autre. N'entoure "
    "JAMAIS une phrase entière de crochets, n'écris JAMAIS de didascalie entre crochets "
    "(pas de [rire], [soupir], etc.), et n'utilise pas de crochets ailleurs. La plupart du temps, "
    "parle simplement, sans aucun tag."
)

_VOICE_GREETING_INSTRUCTION = (
    "Tu viens tout juste d'être invité et de rejoindre le salon vocal. Salue les personnes "
    "présentes brièvement et naturellement, en une seule phrase, dans ton style, à l'oral."
)


def _voice_system(bot, speaker_label: str = "", memory_context: str = "", present_label: str = "") -> str:
    """Construit le system prompt vocal (persona + émotions + contexte du salon)."""
    system_prompt = bot.prompts.build_voice_system(
        emotion_state=bot.emotion.get_state(),
        memory_context=memory_context,
        speaker_label=speaker_label,
        persona_block=bot.persona.build_prompt_block(),
        emotion_directives=bot.persona.emotion_directives,
        weekday_directives=bot.persona.weekday_directives,
        composite_directives=bot.persona.composite_directives,
        secondary_directives=bot.persona.secondary_directives,
        active_secondaries=bot.emotion.get_secondary_emotions(),
    )
    system_prompt = f"{system_prompt}\n\n{_VOICE_TARGET_NOTICE}"
    if present_label:
        system_prompt += (
            f"\n\nPersonnes actuellement dans le salon vocal avec toi : {present_label}. "
            "Tu es déjà présent avec elles depuis un moment — ne les re-salue pas à chaque message, "
            "discute normalement."
        )
    return system_prompt


async def generate_voice_greeting(bot, present_label: str = "", newcomer: str | None = None) -> str:
    """Salutation parlée : à l'arrivée de Wally, ou à l'arrivée d'un nouveau venu (`newcomer`)."""
    try:
        system_prompt = _voice_system(bot, present_label=present_label)
        if newcomer:
            instruction = (
                f"{newcomer} vient à l'instant de rejoindre le salon vocal où tu es déjà installé. "
                f"Accueille {newcomer} par son nom, brièvement et naturellement, en une seule phrase."
            )
        else:
            instruction = _VOICE_GREETING_INSTRUCTION
        messages = [{"role": "user", "content": instruction}]
        reply = await bot.llm.complete(system_prompt, messages, purpose="discord_voice_greeting")
        return reply or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("voice greeting a échoué: {e}", e=e)
        return ""


async def generate_voice_reply(
    bot,
    speaker_label: str,
    transcript: str,
    history: list[dict],
    tools: list[dict],
    tool_executor,
    speaker_user_id: str,
    present_label: str = "",
) -> str:
    """Assemble system_prompt (persona+émotions+présents) + messages, appelle complete_with_tools.

    `speaker_user_id` est le raw Discord snowflake (sans préfixe "discord:").
    """
    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id=speaker_user_id, query=transcript, limit=3
        )
    except Exception as e:
        logger.warning("voice memory.search a échoué: {e}", e=e)
        memory_context = ""

    system_prompt = _voice_system(
        bot, speaker_label=speaker_label, memory_context=memory_context or "",
        present_label=present_label,
    )

    # L'historique contient déjà la parole courante (consignée par handle_transcript),
    # avec tout le fil de groupe (chaque réplique préfixée du nom du locuteur).
    reply, _tools_called = await bot.llm.complete_with_tools(
        system_prompt, list(history), tools, tool_executor,
        purpose="discord_voice",
    )
    return reply or ""


_HISTORY_MAX = 20  # fenêtre de contexte de groupe (toutes personnes confondues)


async def handle_transcript(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str
) -> None:
    """Consigne la parole dans le fil de groupe ; répond si pertinent (une réponse à la fois)."""
    transcript = (transcript or "").strip()
    if not transcript or service.channel_id is None:
        return

    # 1. Toujours consigner la parole dans le fil de conversation (contexte de groupe complet),
    #    même si Wally ne répond pas : il doit suivre ce que les gens se disent entre eux.
    service.history.append({"role": "user", "content": f"{speaker_label}: {transcript}"})
    service.history[:] = service.history[-_HISTORY_MAX:]

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_activity(
                channel_id=service.channel_id, author=speaker_label, content=transcript
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice notify_activity a échoué: {e}", e=e)

    # 2. Une seule réponse à la fois : si Wally répond déjà, la parole est juste consignée
    #    (il en tiendra compte dans sa prochaine réponse). Réservation atomique (aucun await ici).
    if getattr(service, "is_responding", False):
        return
    service.is_responding = True
    try:
        # Filet déterministe : demande explicite de quitter le vocal → on déconnecte vraiment
        # (sans dépendre du tool-calling du LLM, qui dit parfois "ok je pars" sans agir).
        if _is_leave_request(transcript):
            logger.info("voice: demande de départ détectée → déconnexion")
            try:
                await service.speak("Ok, je vous laisse. À plus !")
            except Exception:  # noqa: BLE001
                pass
            await service.leave()
            return

        # Skip le gate si Wally est explicitement nommé → réponse plus rapide.
        named = False
        try:
            trigger_names = [bot.config.bot.name, *(bot.config.bot.trigger_names or [])]
            named = _is_named(transcript, trigger_names)
        except Exception:  # noqa: BLE001
            pass

        gate = getattr(bot, "response_gate", None)
        decision = "RESPOND"
        if gate is not None and not named:
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
            except Exception as e:  # noqa: BLE001
                logger.warning("voice gate.decide a échoué, fallback RESPOND: {e}", e=e)

        if decision != "RESPOND":
            logger.info("voice: gate={d}, Wally ne parle pas", d=decision)
            return

        try:
            present_label = ", ".join(service.members_names())
        except Exception:  # noqa: BLE001
            present_label = ""

        tools = getattr(service, "voice_tools", [])
        tool_executor = getattr(service, "tool_executor", None)
        try:
            text = await generate_voice_reply(
                bot=bot,
                speaker_label=speaker_label,
                transcript=transcript,
                history=list(service.history),  # contient déjà la parole courante + le fil de groupe
                tools=tools,
                tool_executor=tool_executor,
                speaker_user_id=speaker_user_id,
                present_label=present_label,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("voice generate_voice_reply a échoué: {e}", e=e)
            return

        if not text:
            return

        await service.speak(text)
        service.history.append({"role": "assistant", "content": text})
        service.history[:] = service.history[-_HISTORY_MAX:]

        try:
            if getattr(bot, "cognitive_loop", None) is not None:
                bot.cognitive_loop.notify_reply(service.channel_id, content=text)
        except Exception as e:  # noqa: BLE001
            logger.warning("voice notify_reply a échoué: {e}", e=e)
    finally:
        service.is_responding = False
