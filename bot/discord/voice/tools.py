"""Outils LLM pour le contexte vocal (join_voice / leave_voice)."""
import asyncio
import json

from loguru import logger

from bot.core.web_search import WEB_SEARCH_TOOL
from bot.discord.voice.brain import generate_search_filler

VOICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "join_voice",
            "description": (
                "Quand quelqu'un te demande de venir/rejoindre le salon vocal "
                "(ex: 'viens en vocal', 'rejoins-nous'). Tu rejoins le salon vocal de la personne."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leave_voice",
            "description": (
                "Quand on te demande de quitter/partir du salon vocal "
                "(ex: 'quitte le vocal', 'tu peux partir', 'dégage du vocal')."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


async def build_voice_tools(bot) -> list[dict]:
    """Liste des outils proposés en vocal, selon ce qui est disponible."""
    tools = list(VOICE_TOOLS)
    web = getattr(bot, "web_search", None)
    if web is not None and web.available and not await web.is_quota_exceeded():
        tools.append(WEB_SEARCH_TOOL)
    from bot.discord.handlers import _NOTE_TOOLS
    tools.extend(_NOTE_TOOLS)
    action_service = getattr(bot, "action_service", None)
    if action_service is not None:
        tools.extend(action_service.get_tool_definitions())
    return tools


async def _search_aloud(bot, service, query: str) -> str:
    """Cherche sur le web en « parlant tout haut » : amorce + bruits pendant l'attente."""
    filler_task = asyncio.create_task(generate_search_filler(bot, query))
    search_task = asyncio.create_task(bot.web_search.search(query, platform="discord"))
    try:
        filler = await filler_task
        await service.speak(filler.get("amorce") or "")
        for bruit in filler.get("bruits") or []:
            if search_task.done():
                break
            await service.speak(bruit)
    except Exception as e:  # noqa: BLE001
        logger.warning("_search_aloud filler a échoué: {e}", e=e)
    return await search_task


def make_voice_tool_executor(bot, service, current_speaker_id):
    """Construit l'exécuteur d'outils pour le contexte vocal.

    Args:
        bot: instance discord.Bot
        service: VoiceService
        current_speaker_id: callable() -> str | None — id Discord du locuteur courant
    """

    async def executor(name: str, arguments: str) -> str:
        try:
            _ = json.loads(arguments or "{}")
        except Exception:  # noqa: BLE001
            pass

        if name == "leave_voice":
            speaker = current_speaker_id()
            if speaker is None or int(speaker) not in service.members_in_channel():
                logger.info("voice tool: leave_voice refusé — locuteur absent du salon")
                return json.dumps(
                    {"status": "denied", "message": "Seul un membre du salon peut me faire partir."}
                )
            await service.speak("ok, je vous laisse")
            await service.leave()
            logger.info("voice tool: leave_voice exécuté")
            return json.dumps({"status": "ok", "message": "Quitté le salon vocal."})

        if name == "join_voice":
            # En contexte vocal, Wally est déjà connecté ; le join réel se fait côté texte (Task 7).
            return json.dumps({"status": "ok", "message": "Déjà en vocal."})

        if name == "web_search":
            args = {}
            try:
                args = json.loads(arguments or "{}")
            except Exception:  # noqa: BLE001
                pass
            query = (args.get("query") or "").strip()
            if not query:
                return json.dumps({"status": "error", "message": "Requête vide."})
            return await _search_aloud(bot, service, query)

        if name == "save_persistent_note":
            a = json.loads(arguments or "{}")
            await bot.db.upsert_persistent_note(a["title"], a["content"])
            return json.dumps({"status": "ok", "message": f"Note '{a['title']}' sauvegardée."})

        if name == "delete_persistent_note":
            a = json.loads(arguments or "{}")
            deleted = await bot.db.delete_persistent_note(a["title"])
            if deleted:
                return json.dumps({"status": "ok", "message": f"Note '{a['title']}' supprimée."})
            return json.dumps({"status": "not_found", "message": f"Note '{a['title']}' introuvable."})

        if name in ("create_action_task", "cancel_action_task", "list_action_tasks"):
            from bot.discord.handlers import _resolve_discord_roles
            a = json.loads(arguments or "{}")
            speaker_id = current_speaker_id()
            channel = getattr(service, "_channel", None)
            member = None
            if channel is not None and speaker_id is not None:
                member = next((m for m in channel.members if str(m.id) == str(speaker_id)), None)
            user_roles = _resolve_discord_roles(member) if member is not None else []
            admin_ids = [str(x) for x in getattr(bot.config, "admin_ids", [])]
            if speaker_id is not None and str(speaker_id) in admin_ids:
                user_roles.append("admin")
            # Création → besoin d'un salon cible (la chambre). Refus propre sinon.
            if name == "create_action_task":
                bedroom = getattr(bot.config.bot, "bedroom_channel_id", None)
                if bedroom is None:
                    return json.dumps({"status": "denied",
                                       "message": "Je ne sais pas encore où poster tes rappels."})
                channel_id = str(bedroom)
            else:
                channel_id = None
            guild_id = str(channel.guild.id) if channel is not None and getattr(channel, "guild", None) else None
            result = await bot.action_service.execute_tool(
                name, a, user_id=str(speaker_id), platform="discord",
                user_roles=user_roles, channel_id=channel_id, guild_id=guild_id,
            )
            return json.dumps(result)

        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    return executor
