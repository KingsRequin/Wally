"""Cerveau vocal : branchement gate + génération de la réponse parlée."""
import asyncio
import re
from collections import OrderedDict
from difflib import SequenceMatcher

from loguru import logger

from bot.core.text_clean import retirer_tirets_cadratins
from bot.core.voice_transcript import active_voice_transcript
from bot.discord.voice.style import available_tags


def _history_to_context(history: list[dict], bot_name: str = "") -> list[dict]:
    """Convertit l'historique vocal ({role, 'label: texte'}) en {author, content} pour l'analyse émotion."""
    ctx: list[dict] = []
    for m in history[-8:]:
        content = m.get("content", "")
        if m.get("role") == "assistant":
            ctx.append({"author": bot_name or "moi", "content": content})
        else:
            author, sep, txt = content.partition(": ")
            ctx.append({"author": author, "content": txt} if sep else {"author": "?", "content": content})
    return ctx


async def _voice_post_emotion(bot, speaker_user_id, speaker_label, transcript,
                              channel_id, channel_name, context_messages) -> None:
    """En fond : fait bouger l'humeur de Wally + affinité + faits perso, à partir de la parole entendue."""
    try:
        deltas = await bot.emotion.process_message(
            transcript,
            context_messages=context_messages,
            trigger_user=speaker_user_id,
            channel_id=str(channel_id),
            platform="discord",
            user_id=speaker_user_id,
            beloved=bot.persona.is_beloved("discord", speaker_user_id),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice emotion.process_message a échoué: {e!r}", e=e)
        return
    if deltas and deltas.get("user_facts"):
        origin = (f"Vocal {channel_name}").strip()
        for fact in deltas["user_facts"]:
            try:
                await bot.memory.add("discord", speaker_user_id, fact,
                                     username=speaker_label, origin=origin)
            except Exception as e:  # noqa: BLE001
                logger.warning("voice memory.add (user_fact) a échoué: {e!r}", e=e)

_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)

# Part des mots significatifs de l'énoncé qui doivent se retrouver dans ce que
# Wally dit pour que ce soit son écho. Haut VOLONTAIREMENT : sous ce seuil, une
# vraie phrase partageant deux mots avec la sienne serait jetée, et c'est
# exactement le silence qu'on corrige. Une phrase humaine dépasse rarement la
# moitié — elle apporte des mots à elle.
_ECHO_RECOUVREMENT_MIN = 0.8

# Tâches de fond détachées, gardées en vie le temps qu'elles s'achèvent.
_TACHES_FOND: set[asyncio.Task] = set()


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


# Mots d'arrêt stricts (peu susceptibles d'apparaître dans une réponse normale de Wally,
# pour éviter qu'il se coupe lui-même via sa propre voix captée par un micro).
_STOP_RE = re.compile(
    r"\b(stop|tais[\s-]?toi|taisez[\s-]?vous|chut|la ferme|ta gueule|silence|"
    r"stp arr[êe]te|wally stop)\b",
    re.IGNORECASE,
)


def _is_stop_request(transcript: str) -> bool:
    """Vrai si la parole est un ordre d'arrêt (pour interrompre Wally pendant qu'il parle)."""
    return bool(_STOP_RE.search(transcript or ""))


def est_un_echo(entendu: str, dit: str) -> bool:
    """Vrai si `entendu` est la voix de Wally revenue par le micro d'un auditeur.

    Sans casque, ce que Wally dit sort des enceintes, rentre dans le micro de la
    personne et lui est ATTRIBUÉ par Discord. Il s'entendait alors lui-même, se
    répondait, et le fact_extractor rangeait ses propres phrases comme des faits
    sur elle. `is_speaking` servait de filtre — il jetait TOUTE parole entendue
    pendant qu'il parlait, vraie ou non, alors que répondre à quelqu'un pendant
    qu'il parle est le cas normal d'une conversation. Et Wally parle en
    arrivant : la fenêtre où on lui répond était exactement celle où il
    n'écoutait pas.

    Le discriminant n'est pas le silence, c'est le CONTENU : on sait mot pour
    mot ce qu'il est en train de dire. Le chevauchement de VOCABULAIRE, et non
    la ressemblance de chaîne — le STT rend l'écho déformé, tronqué, sans
    ponctuation, souvent un fragment au milieu de la phrase.

    Le doute profite au locuteur, comme pour le plancher d'énoncé : rater un
    écho coûte une réponse de trop, rater une phrase rend Wally muet devant
    quelqu'un qui lui parle — le défaut qu'on est en train de corriger.
    """
    if not entendu or not dit:
        return False
    mots_dits = {m for m in _WORD_RE.findall(dit.lower()) if len(m) >= 3}
    mots_entendus = [m for m in _WORD_RE.findall(entendu.lower()) if len(m) >= 3]
    if not mots_dits or not mots_entendus:
        return False
    communs = sum(1 for m in mots_entendus if m in mots_dits)
    return communs / len(mots_entendus) >= _ECHO_RECOUVREMENT_MIN


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


# Mots interrogatifs en début de phrase (le STT ne restitue pas toujours le « ? »).
_QUESTION_STARTS = (
    "est-ce", "est ce", "qu'est", "qu est", "c'est quoi", "c est quoi", "c'est qui",
    "qui est", "qui veut", "comment", "pourquoi", "combien", "quand", "quel", "quelle",
    "quels", "quelles", "où est", "ou est", "où es", "ou es",
)


def _is_question(transcript: str) -> bool:
    """Vrai si la parole est (vraisemblablement) une question adressée au groupe."""
    t = (transcript or "").strip().lower()
    if not t:
        return False
    if t.endswith("?") or " ?" in t:
        return True
    return any(t.startswith(w) for w in _QUESTION_STARTS)


def _should_respond_voice(transcript: str, history: list[dict], named: bool) -> bool:
    """Décide localement (0 appel LLM) si Wally prend la parole en vocal.

    Il répond quand : on le nomme, c'est une question au groupe, ou l'échange est en cours
    (il est intervenu dans les deux derniers tours). Sinon il écoute les gens se parler.
    `history` contient déjà la parole courante en dernier ; on regarde les tours précédents.
    """
    if named or _is_question(transcript):
        return True
    recent = history[:-1][-2:]  # deux tours avant la parole courante
    return any(m.get("role") == "assistant" for m in recent)

_VOICE_CONTEXT_NOTICE = (
    "CONTEXTE : tu es actuellement connecté dans un salon VOCAL Discord et tu parles à voix "
    "haute. Tu ENTENDS les gens parler (transcription) et tu leur réponds ORALEMENT, ce n'est "
    "pas du texte écrit. C'est une conversation de GROUPE : plusieurs personnes peuvent parler, "
    "et tu en fais partie comme un participant parmi les autres. Dans l'historique, chaque réplique "
    "est préfixée par le nom de la personne qui parle (ex 'Alex: ...'). Suis le fil GLOBAL de la "
    "discussion, tiens compte de ce que se disent les gens entre eux, et interviens naturellement, "
    "tu n'as pas à répondre à chaque phrase ni à chaque personne séparément. "
    "Réponds en une à deux phrases courtes, naturelles à l'oral, sans "
    "formatage, sans markdown, sans emoji. Réponds UNIQUEMENT avec ton propre texte."
)

# Les crochets ne servent QU'aux tons. Sans cette interdiction, il écrit des
# didascalies ([rire], [soupir]) : elles sont retirées avant la synthèse, donc
# c'est de la réplique perdue — il croit avoir soupiré, personne n'entend rien.
_NO_BRACKETS = (
    "N'entoure JAMAIS une phrase entière de crochets, n'écris JAMAIS de didascalie entre "
    "crochets (pas de [rire], [soupir], etc.), et n'utilise pas de crochets ailleurs."
)


def _tone_notice(voice: str) -> str:
    """Consigne de ton, dérivée des styles que la voix montée rend RÉELLEMENT.

    Écrite en dur, la liste mentait des deux côtés : elle proposait huit tons à
    une voix MAI qui en porte dix-huit, et les mêmes huit à une voix qui n'en
    porte aucun. Un ton promis mais non rendu part en tag inutile ; un ton rendu mais
    absent de la liste laisse la moitié du mécanisme d'émotion sans utilisateur.
    """
    tags = available_tags(voice)
    if not tags:
        return f"TON DE VOIX : ta voix ne porte pas de ton particulier. {_NO_BRACKETS}"
    liste = ", ".join(f"[{tag}]" for tag in tags)
    return (
        "TON DE VOIX : par défaut ta voix suit ton humeur. Tu peux choisir un ton précis "
        "UNIQUEMENT en plaçant UN SEUL mot-tag entre crochets au TOUT DÉBUT de ta phrase, "
        f"parmi exactement : {liste}. "
        f"Exemple correct : '[{tags[0]}] viens voir ça'. "
        "RÈGLES STRICTES sur les crochets : un seul mot-tag, au tout début, rien d'autre. "
        f"{_NO_BRACKETS} La plupart du temps, parle simplement, sans aucun tag."
    )


def _style_voice(bot) -> str:
    """Voix vocale réellement montée, "" si le vocal n'est pas là.

    Demandée au service plutôt qu'à la config : c'est le TTS construit qui sait
    s'il porte des tons, pas `cfg.azure_voice` qui reste renseignée même sous
    un provider qui les ignore.
    """
    service = getattr(bot, "voice_service", None) or getattr(
        getattr(bot, "discord_bot", None), "voice_service", None)
    return getattr(service, "style_voice", "") or ""


def _voice_system(bot, speaker_label: str = "", memory_context: str = "",
                  present_label: str = "", channel_name: str = "", activity_label: str = "",
                  speaker_user_id: str = "") -> str:
    """Construit le system prompt vocal (persona + émotions + contexte du salon)."""
    user_directive = bot.persona.user_directive("discord", speaker_user_id) if speaker_user_id else None
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
        user_directive=user_directive,
    )
    system_prompt = f"{system_prompt}\n\n{_VOICE_CONTEXT_NOTICE}\n{_tone_notice(_style_voice(bot))}"
    if channel_name:
        system_prompt += f"\n\nTu es dans le salon vocal « {channel_name} »."
    if present_label:
        system_prompt += (
            f"\n\nPersonnes actuellement dans le salon vocal avec toi : {present_label}. "
            "Tu es déjà présent avec elles depuis un moment, ne les re-salue pas à chaque message, "
            "discute normalement."
        )
    if activity_label:
        system_prompt += (
            f"\n\nCe que font les présents en ce moment (jeu, musique…) : {activity_label}. "
            "Tu peux le remarquer ou en parler si c'est pertinent."
        )
    return system_prompt


async def generate_voice_greeting(bot, present_label: str = "", newcomer: str | None = None,
                                  channel_name: str = "", activity_label: str = "",
                                  inviter: str | None = None, newcomer_user_id: str = "") -> str:
    """Salutation parlée : à l'arrivée de Wally, ou à l'arrivée d'un nouveau venu (`newcomer`).

    `inviter` : nom de la personne qui a demandé à Wally de venir (cas arrivée de Wally)."""
    try:
        if newcomer:
            # Wally est déjà installé → on garde le contexte « présents depuis un moment » du system.
            system_prompt = _voice_system(bot, present_label=present_label, channel_name=channel_name,
                                          activity_label=activity_label, speaker_user_id=newcomer_user_id)
            instruction = (
                f"{newcomer} vient à l'instant de rejoindre le salon vocal où tu es déjà installé. "
                f"Accueille {newcomer} par son nom, brièvement et naturellement, en une seule phrase."
            )
        else:
            # Arrivée de Wally : on NE met PAS les présents dans le system (il dirait « depuis un
            # moment »), on les liste dans l'instruction et on borne le singulier/pluriel.
            system_prompt = _voice_system(bot, channel_name=channel_name, activity_label=activity_label)
            lines: list[str] = []
            if inviter:
                lines.append(f"{inviter} t'a demandé de venir dans le salon vocal, et tu viens d'arriver.")
            else:
                lines.append("Tu viens tout juste de rejoindre le salon vocal.")
            if present_label:
                lines.append(f"Personnes réellement présentes dans le salon : {present_label}.")
            lines.append(
                "Dis bonjour en arrivant, brièvement et naturellement, en une seule phrase, dans ton "
                "style. Adresse-toi uniquement aux personnes réellement présentes listées ci-dessus, "
                "n'en invente aucune, et n'emploie « vous » que s'il y a vraiment plusieurs personnes, "
                "sinon parle au singulier."
            )
            instruction = " ".join(lines)
        messages = [{"role": "user", "content": instruction}]
        reply = await bot.llm.complete(system_prompt, messages, purpose="discord_voice_greeting")
        return reply or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("voice greeting a échoué: {e!r}", e=e)
        return ""


_FILLER_FALLBACK = {
    "amorce": "attends, je regarde ça",
    "bruits": ["mh...", "ok je vois...", "deux secondes..."],
}

_FILLER_SCHEMA = {
    "type": "object",
    "properties": {
        "amorce": {"type": "string"},
        "bruits": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["amorce", "bruits"],
}


async def generate_search_filler(bot, query: str) -> dict:
    """Génère, dans le style/l'humeur de Wally, une amorce parlée (« attends je cherche »)
    et 2-3 petits bruits de réflexion. Un seul appel LLM ; repli déterministe si échec."""
    try:
        system_prompt = _voice_system(bot)
        instruction = (
            "Tu vas chercher une information sur internet, ça prend quelques secondes. "
            f"Sujet de la recherche : « {query} ». "
            "Donne 'amorce' : une courte phrase parlée, dans ton style, qui annonce que tu "
            "regardes (ex. « attends, je vérifie ça »). Donne 'bruits' : 2 à 3 très courtes "
            "onomatopées/interjections de réflexion à dire pendant que ça charge "
            "(ex. « mh... », « ok je vois... »). Pas de markdown, pas d'emoji."
        )
        messages = [{"role": "user", "content": instruction}]
        out = await bot.llm_secondary.complete_structured(
            system_prompt, messages, _FILLER_SCHEMA,
            schema_name="search_filler", purpose="discord_voice_search_filler",
        )
        amorce = (out.get("amorce") or "").strip()
        bruits = [b.strip() for b in (out.get("bruits") or []) if b and b.strip()]
        if not amorce:
            return dict(_FILLER_FALLBACK)
        return {"amorce": amorce, "bruits": bruits}
    except Exception as e:  # noqa: BLE001
        logger.warning("generate_search_filler a échoué: {e!r}", e=e)
        return dict(_FILLER_FALLBACK)


async def generate_voice_reply(
    bot,
    speaker_label: str,
    transcript: str,
    history: list[dict],
    tools: list[dict],
    tool_executor,
    speaker_user_id: str,
    present_label: str = "",
    channel_name: str = "",
    activity_label: str = "",
) -> str:
    """Assemble system_prompt (persona+émotions+présents) + messages, appelle complete_with_tools.

    `speaker_user_id` est le raw Discord snowflake (sans préfixe "discord:").
    """
    try:
        memory_context = await bot.memory.search(
            platform="discord", user_id=speaker_user_id, query=transcript, limit=3
        )
    except Exception as e:
        logger.warning("voice memory.search a échoué: {e!r}", e=e)
        memory_context = ""

    # Recall RSS knowledge (patch notes Apex) : le vocal en était privé alors que
    # c'est le chemin où l'on commente le jeu EN JOUANT. Sans lui, une question sur
    # le dernier patch ne recevait qu'un « je sais pas » — exact, faute de données.
    try:
        from bot.discord.handlers import _rss_knowledge_context

        if rss_block := await _rss_knowledge_context(bot, transcript or ""):
            memory_context = f"{memory_context}\n\n{rss_block}" if memory_context else rss_block
    except Exception as e:  # noqa: BLE001 — jamais bloquant pour la réponse
        logger.warning("rss_knowledge (vocal): injection ignorée: {e!r}", e=e)

    system_prompt = _voice_system(
        bot, speaker_label=speaker_label, memory_context=memory_context or "",
        present_label=present_label, channel_name=channel_name, activity_label=activity_label,
        speaker_user_id=speaker_user_id,
    )

    # L'historique contient déjà la parole courante (consignée par handle_transcript),
    # avec tout le fil de groupe (chaque réplique préfixée du nom du locuteur).
    reply, _tools_called = await bot.llm.complete_with_tools(
        system_prompt, list(history), tools, tool_executor,
        purpose="discord_voice",
    )
    return reply or ""


_HISTORY_MAX = 20  # fenêtre de contexte de groupe (toutes personnes confondues)

# Comment Wally se désigne lui-même dans le tampon de conversation vocale. Le
# bloc est rédigé à la 2e personne : « [Toi] » y est sans ambiguïté, là où son
# pseudo l'obligerait à se reconnaître dans une liste de tiers.
_SELF_LABEL = "Toi"


def _remember_line(service, *, role: str, speaker: str, text: str) -> None:
    """Consigne une réplique du vocal — fil LLM du salon ET tampon de contexte écrit.

    Point d'écriture UNIQUE des deux tampons : ils portent la même conversation,
    et deux appelants séparés finissent toujours par diverger le jour où un
    troisième chemin de parole apparaît.

    Le tampon de contexte, lui, ne retient que ce qui est diffusé au live — cf.
    `bot/core/voice_transcript.py`. Ce n'est pas à cet appelant d'en juger.
    """
    # Sa propre réponse entre nue dans le fil : c'est déjà lui qui parle.
    content = f"{speaker}: {text}" if role == "user" else text
    service.history.append({"role": role, "content": content})
    service.history[:] = service.history[-_HISTORY_MAX:]

    feed = active_voice_transcript()
    if feed is None:
        return
    try:
        feed.record(getattr(service, "channel_id", None), speaker, text)
    except Exception as e:  # noqa: BLE001 — un tampon de contexte ne casse pas le vocal
        logger.warning("VoiceTranscript: réplique non consignée: {e!r}", e=e)


async def consigner_et_dire(service, text: str, *, malgre_ecoute: bool = False) -> bool:
    """Consigne la réplique de Wally AU FIL, puis la dit à voix haute.

    Dans cet ordre, et c'est tout le correctif. La parole ENTENDUE est consignée
    à l'instant où le STT la rend, tandis que la réplique ne l'était qu'après
    `speak()` — donc après la synthèse Azure ET la lecture audio, plusieurs
    secondes. Or répondre à Wally pendant qu'il parle est le cas NORMAL d'une
    conversation : sa question s'insérait alors APRÈS la réponse qu'elle venait
    de provoquer, et il ne pouvait plus relier les deux.

    C'est le moment où la réplique est DÉCIDÉE qui la situe dans la
    conversation, pas la fin de sa lecture. Une panne de TTS ne troue donc pas
    le fil : il a bien dit ça, même si personne ne l'a entendu.

    PUBLIQUE, et c'est le second correctif : la réponse générée passait par ici,
    mais la SALUTATION d'arrivée, l'accueil d'un nouveau venu et la parole
    commandée par un modérateur allaient droit à `speak()`. Wally disait bonjour
    puis n'avait, pour lui-même, rien dit — et `_should_respond_voice` ne
    voyait aucun tour à enchaîner. Il fallait le nommer à chaque phrase.

    Rend ce que rend `speak()` : VRAI si la parole est sortie. `say_in_voice`
    lit ce retour pour ne pas confirmer une phrase que personne n'a entendue.
    """
    # Le tiret ne s'entend pas à l'oral, mais cette réplique part AUSSI au fil
    # du salon et au tampon de contexte écrit, que Wally relit ensuite ailleurs.
    text = retirer_tirets_cadratins(text)
    _remember_line(service, role="assistant", speaker=_SELF_LABEL, text=text)
    return await service.speak(text, malgre_ecoute=malgre_ecoute)


def _voice_publish(bot, service, type_: str, persist: bool = True, **fields) -> None:
    """Publie un événement de debug vocal sur le feed (live SSE + historique). Jamais bloquant.

    `persist=False` → live seulement (pas d'historique), pour les `partial` STT éphémères.
    """
    feed = getattr(bot, "voice_feed", None)
    if feed is None:
        return
    event = {
        "type": type_,
        "channel_id": str(getattr(service, "channel_id", "")),
        "channel_name": getattr(service, "channel_name", ""),
        **fields,
    }
    try:
        feed.publish(event, persist=persist)
    except Exception as e:  # noqa: BLE001
        logger.warning("voice_feed.publish a échoué: {e!r}", e=e)


async def handle_transcript(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str,
    stt_ms: float = 0.0,
) -> None:
    """Consigne la parole dans le fil de groupe ; répond si pertinent (une réponse à la fois)."""
    transcript = (transcript or "").strip()
    if not transcript or service.channel_id is None:
        return

    # 1. Toujours consigner la parole dans le fil de conversation (contexte de groupe complet),
    #    même si Wally ne répond pas : il doit suivre ce que les gens se disent entre eux.
    _remember_line(service, role="user", speaker=speaker_label, text=transcript)

    # Suivi/debug : ce que le STT a entendu (avec sa latence), publié quoi qu'il advienne.
    _voice_publish(bot, service, "heard", speaker=speaker_label, speaker_id=speaker_user_id,
                   text=transcript, stt_ms=round(stt_ms))

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_activity(
                channel_id=service.channel_id, author=speaker_label, content=transcript,
                relevant=True,  # présence vocale active = interaction qui le concerne
                user_key=f"discord:{speaker_user_id}" if speaker_user_id else None,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice notify_activity a échoué: {e!r}", e=e)

    # Mémoire de groupe : extraction passive de faits durables (comme à l'écrit).
    try:
        bot.fact_extractor.record_message(
            channel_id=str(service.channel_id), platform="discord",
            user_id=speaker_user_id, display_name=speaker_label,
            content=transcript, origin=f"Vocal {service.channel_name}".strip(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("voice fact_extractor.record_message a échoué: {e!r}", e=e)

    # 2. Décider de répondre (une seule réponse à la fois, file d'attente anti-drop).
    await _maybe_respond(bot, service, speaker_user_id, speaker_label, transcript)


# File d'attente multi-locuteurs : pendant que Wally répond, on empile la parole entendue
# au lieu de la jeter. Une entrée par locuteur (coalescing : on garde sa parole la plus
# récente), traitée dans l'ordre d'arrivée (FIFO). Bornée pour ne pas répondre à du périmé —
# c'est ce qui évite le « il répond aux questions précédentes » quand le groupe s'emballe.
_PENDING_TTL_S = 18.0   # au-delà, une parole en attente est considérée caduque et ignorée
_PENDING_MAX = 6        # nombre max de locuteurs en attente (borne le lag accumulé)


def _now() -> float:
    """Horloge monotone (boucle asyncio) — isolée pour pouvoir la simuler en test."""
    return asyncio.get_running_loop().time()


def _pending_dict(service) -> OrderedDict:
    """File des paroles en attente, indexée par locuteur. Initialisée paresseusement."""
    q = getattr(service, "_pending_queue", None)
    if not isinstance(q, OrderedDict):
        q = OrderedDict()
        service._pending_queue = q
    return q


def _enqueue_pending(service, speaker_user_id: str, speaker_label: str, transcript: str) -> None:
    """Empile (ou rafraîchit) la parole d'un locuteur en attente, en bornant la file."""
    q = _pending_dict(service)
    q.pop(speaker_user_id, None)  # coalescing : ré-insère en fin avec la parole la plus récente
    q[speaker_user_id] = (speaker_label, transcript, _now())
    while len(q) > _PENDING_MAX:
        q.popitem(last=False)  # évince le plus ancien locuteur en attente


def _next_pending(service):
    """Défile la prochaine parole en attente encore valide (FIFO), en sautant les périmées."""
    q = _pending_dict(service)
    now = _now()
    while q:
        sid, (label, transcript, ts) = q.popitem(last=False)
        if now - ts <= _PENDING_TTL_S:
            return (sid, label, transcript)
        logger.info("voice: parole en attente périmée ignorée ({label})", label=label)
    return None


async def _maybe_respond(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str
) -> None:
    """Sérialise les réponses (une à la fois) SANS jeter la parole des autres locuteurs.

    Si Wally répond déjà, la parole est empilée par locuteur (file FIFO bornée) au lieu d'être
    ignorée : chaque personne qui s'adresse à lui est traitée à son tour. On ne garde qu'une
    parole par locuteur (la plus récente) et on abandonne ce qui devient périmé.
    """
    if getattr(service, "is_responding", False):
        _enqueue_pending(service, speaker_user_id, speaker_label, transcript)
        return
    service.is_responding = True
    try:
        current = (speaker_user_id, speaker_label, transcript)
        while current is not None:
            await _respond_once(bot, service, *current)
            # Un départ survenu pendant ce tour (« dégage », outil `leave_voice`)
            # a vidé la file dans `leave()` : `_next_pending` rend None et la
            # boucle s'arrête d'elle-même. Sans ça, chaque parole restante
            # coûtait un appel LLM complet pour un `speak()` devenu no-op, et
            # `_voice_post_emotion` recevait un `channel_id` None qu'il
            # transformait en la chaîne « None ».
            current = _next_pending(service)
    finally:
        service.is_responding = False


async def _respond_once(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str
) -> None:
    """Produit (au plus) une réponse parlée à une parole donnée. Le verrou est géré par l'appelant."""
    # Qui parle DANS CE TOUR : l'exécuteur d'outils lisait un champ du service,
    # écrit à chaque transcription entendue. Une parole défilée de la file était
    # donc traitée sous l'identité du dernier locuteur ENTENDU — et `leave_voice`
    # comme `create_action_task` s'autorisaient contre cette mauvaise personne.
    # L'identité voyage maintenant avec le tour de parole, isolée par tâche.
    from bot.discord.voice.tools import reset_current_speaker, set_current_speaker

    _speaker_token = set_current_speaker(speaker_user_id)
    try:
        await _respond_once_inner(bot, service, speaker_user_id, speaker_label, transcript)
    finally:
        reset_current_speaker(_speaker_token)


async def _respond_once_inner(
    bot, service, speaker_user_id: str, speaker_label: str, transcript: str
) -> None:
    t0 = asyncio.get_running_loop().time()

    def _gen_ms() -> int:
        return round((asyncio.get_running_loop().time() - t0) * 1000)

    wally_name = getattr(getattr(bot, "config", None), "bot", None)
    wally_name = getattr(wally_name, "name", None) or "Wally"

    # Heuristique locale rapide (0 appel LLM) : décide si Wally prend la parole.
    named = False
    try:
        trigger_names = [bot.config.bot.name, *(bot.config.bot.trigger_names or [])]
        named = _is_named(transcript, trigger_names)
    except Exception:  # noqa: BLE001
        pass

    # Filet déterministe : demande explicite de quitter le vocal → on déconnecte vraiment
    # (sans dépendre du tool-calling du LLM, qui dit parfois "ok je pars" sans agir).
    #
    # Mais SEULEMENT s'il est nommé. Le test venait avant, si bien qu'une phrase
    # lancée à l'écran ou à quelqu'un d'autre le faisait partir en pleine partie :
    # « putain dégage », « casse-toi de mon écran », « je me déconnecte deux
    # minutes » déclenchaient tous le départ. C'est la même règle que sur les
    # autres chemins — lui parler, c'est le nommer.
    if named and _is_leave_request(transcript):
        logger.info("voice: demande de départ détectée → déconnexion")
        try:
            await service.speak("Ok, je vous laisse. À plus !")
        except Exception:  # noqa: BLE001
            pass
        _voice_publish(bot, service, "reply", speaker=wally_name,
                       text="Ok, je vous laisse. À plus !", gen_ms=_gen_ms())
        await service.leave()
        return

    if not _should_respond_voice(transcript, service.history, named):
        # Le texte est DANS la ligne : sans lui, un silence de Wally ne se
        # diagnostique qu'en ouvrant `voice_events` en base, et on ne sait pas
        # si c'est la décision qui a raté ou le STT qui a rendu du charabia.
        logger.info("voice: parole pas adressée à Wally → il écoute — « {t} »",
                    t=transcript[:120])
        _voice_publish(bot, service, "ignored", speaker=speaker_label, speaker_id=speaker_user_id,
                       text=transcript, reason="pas adressé à Wally")
        return

    # Feedback de latence : bref bip « j'ai entendu, je réfléchis » avant la génération LLM.
    try:
        await service.play_cue()
    except Exception as e:  # noqa: BLE001
        logger.warning("voice play_cue a échoué: {e!r}", e=e)

    try:
        present_label = ", ".join(service.members_names())
    except Exception:  # noqa: BLE001
        present_label = ""
    try:
        activity_label = " ; ".join(service.members_activity())
    except Exception:  # noqa: BLE001
        activity_label = ""

    from bot.discord.voice.tools import build_voice_tools
    tools = await build_voice_tools(bot)
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
            channel_name=getattr(service, "channel_name", ""),
            activity_label=activity_label,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("voice generate_voice_reply a échoué: {e!r}", e=e)
        return

    if not text:
        _voice_publish(bot, service, "ignored", speaker=speaker_label, speaker_id=speaker_user_id,
                       text=transcript, reason="réponse vide")
        return

    # Consignée AVANT d'être prononcée : `speak()` dure toute la lecture, et
    # l'interlocuteur qui répond pendant ce temps passait devant la question
    # qu'il était en train de répondre.
    await consigner_et_dire(service, text)
    # Suivi/debug : la réponse de Wally + latence depuis la décision (gate + génération + TTS).
    _voice_publish(bot, service, "reply", speaker=wally_name, text=text, gen_ms=_gen_ms())

    try:
        if getattr(bot, "cognitive_loop", None) is not None:
            bot.cognitive_loop.notify_reply(service.channel_id, content=text)
    except Exception as e:  # noqa: BLE001
        logger.warning("voice notify_reply a échoué: {e!r}", e=e)

    # Émotions + affinité, en tâche de fond (n'ajoute pas de latence à la parole).
    try:
        ctx = _history_to_context(service.history, getattr(bot.config.bot, "name", ""))
        # Référence FORTE : sans elle, le ramasse-miettes peut collecter la tâche
        # avant qu'elle ne s'achève. C'était le seul `create_task` nu du projet,
        # et il portait l'humeur, l'affinité et les `user_facts` du vocal —
        # perdus en silence quand la collecte tombait au mauvais moment.
        tache = asyncio.create_task(_voice_post_emotion(
            bot, speaker_user_id, speaker_label, transcript,
            service.channel_id, service.channel_name, ctx,
        ))
        _TACHES_FOND.add(tache)
        tache.add_done_callback(_TACHES_FOND.discard)
    except Exception as e:  # noqa: BLE001
        logger.warning("voice post-emotion a échoué: {e!r}", e=e)
