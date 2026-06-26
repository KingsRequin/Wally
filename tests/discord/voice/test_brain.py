"""Tests pour bot/discord/voice/brain.py — gate + génération réponse vocale."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.intelligence.gate import GateDecision
from bot.discord.voice.brain import handle_transcript, generate_voice_reply


def _bot(decision="RESPOND"):
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0
    }
    bot.emotion.get_secondary_emotions.return_value = []
    bot.memory.search = AsyncMock(return_value="")
    bot.llm.complete_with_tools = AsyncMock(return_value=("salut à tous", []))
    bot.response_gate.decide = AsyncMock(
        return_value=GateDecision(decision=decision, reason="r")
    )
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    # Persona attributes — must mirror what _respond uses
    bot.persona.build_prompt_block.return_value = "PERSONA_BLOCK"
    bot.persona.emotion_directives = {"joy_mid": "tu es joyeux"}
    bot.persona.weekday_directives = {}
    bot.persona.composite_directives = {}
    bot.persona.secondary_directives = {}
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


@pytest.mark.asyncio
async def test_persona_parity_in_voice_prompt():
    """Vérifie que build_voice_system reçoit bien le bloc persona + toutes les
    directives émotionnelles, comme le chemin texte dans _respond."""
    bot = _bot("RESPOND")
    service = MagicMock()
    service.speak = AsyncMock()
    service.history = []

    await handle_transcript(bot, service, "610550333042589752", "Bob (@bob)", "bonjour")

    # build_voice_system doit être appelé avec les args persona
    bot.prompts.build_voice_system.assert_called_once()
    call_kwargs = bot.prompts.build_voice_system.call_args.kwargs

    assert call_kwargs.get("persona_block") == "PERSONA_BLOCK", (
        "persona_block absent ou vide dans l'appel à build_voice_system"
    )
    assert call_kwargs.get("emotion_directives") == {"joy_mid": "tu es joyeux"}, (
        "emotion_directives absent dans l'appel à build_voice_system"
    )
    assert "weekday_directives" in call_kwargs, "weekday_directives manquant"
    assert "composite_directives" in call_kwargs, "composite_directives manquant"
    assert "secondary_directives" in call_kwargs, "secondary_directives manquant"
    assert "active_secondaries" in call_kwargs, "active_secondaries manquant"

    # build_prompt_block doit avoir été appelé
    bot.persona.build_prompt_block.assert_called_once()


@pytest.mark.asyncio
async def test_history_appended_after_speak():
    """Vérifie que service.history n'est modifié QU'APRÈS service.speak()."""
    bot = _bot("RESPOND")
    service = MagicMock()
    history_snapshot_at_speak: list = []

    async def capture_speak(text):
        # Capture l'état du history au moment exact de l'appel speak
        history_snapshot_at_speak.extend(list(service.history))

    service.speak = AsyncMock(side_effect=capture_speak)
    service.history = []

    await handle_transcript(bot, service, "42", "Alice (@alice)", "wally ?")

    # Au moment de speak(), history doit encore être vide
    assert history_snapshot_at_speak == [], (
        "service.history a été modifié AVANT service.speak()"
    )
    # Après handle_transcript, history contient user + assistant
    assert len(service.history) == 2


@pytest.mark.asyncio
async def test_generate_voice_reply_uses_speaker_user_id():
    """Vérifie que generate_voice_reply passe le bon user_id à memory.search."""
    bot = _bot()
    await generate_voice_reply(
        bot=bot,
        speaker_label="Alice",
        transcript="test",
        history=[],
        tools=[],
        tool_executor=None,
        speaker_user_id="123456789",
    )
    bot.memory.search.assert_awaited_once()
    call_kwargs = bot.memory.search.call_args.kwargs
    assert call_kwargs.get("user_id") == "123456789", (
        "memory.search appelé avec un user_id incorrect"
    )
