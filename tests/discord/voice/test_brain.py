"""Tests pour bot/discord/voice/brain.py — gate + génération réponse vocale."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.gate import GateDecision
from bot.discord.voice.brain import handle_transcript


def _bot(decision="RESPOND"):
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0
    }
    bot.memory.search = AsyncMock(return_value="")
    bot.llm.complete_with_tools = AsyncMock(return_value=("salut à tous", []))
    bot.response_gate.decide = AsyncMock(
        return_value=GateDecision(decision=decision, reason="r")
    )
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    return bot


@pytest.mark.asyncio
async def test_respond_triggers_speak():
    bot = _bot("RESPOND")
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally tu es là ?")
    service.speak.assert_awaited_once()
    assert service.speak.await_args.args[0] == "salut à tous"


@pytest.mark.asyncio
async def test_ignore_does_not_speak():
    bot = _bot("IGNORE")
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []
    await handle_transcript(bot, service, "42", "Alice (@alice)", "blabla")
    service.speak.assert_not_awaited()
