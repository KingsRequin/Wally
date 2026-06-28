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

        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    return executor
