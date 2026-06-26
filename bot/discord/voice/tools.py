"""Outils LLM pour le contexte vocal (join_voice / leave_voice)."""
import json

from loguru import logger

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

        return json.dumps({"status": "error", "message": f"Outil inconnu: {name}"})

    return executor
