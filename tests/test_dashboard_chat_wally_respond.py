# tests/test_dashboard_chat_wally_respond.py
"""Tests for _wally_respond (web chat) — user_directive wiring for Malef."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.dashboard.routes.chat import _wally_respond

MALEF_DISCORD_ID = "706837895063011338"


def make_state():
    state = MagicMock()
    state.config.bot.name = "Wally"

    state.db.get_trust_score = AsyncMock(return_value=0.5)
    state.db.insert_chat_message = AsyncMock(return_value=1)

    state.memory.append_message = MagicMock()
    state.memory.append_prelude = MagicMock()
    state.memory.search = AsyncMock(return_value="")
    state.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])

    state.emotion.get_state = MagicMock(
        return_value={"anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )

    state.persona = MagicMock()
    state.persona.build_prompt_block = MagicMock(return_value="persona block")

    state.prompts.build_system_prompt = MagicMock(return_value="system prompt")
    state.prompts.build_context_block = MagicMock(return_value="")

    state.primary_llm.complete = AsyncMock(return_value="Salut!")
    state.record_response_time = MagicMock()

    state.fact_extractor = None

    return state


@pytest.mark.asyncio
async def test_wally_respond_injects_user_directive_for_target_user():
    state = make_state()
    state.persona.user_directive = MagicMock(
        side_effect=lambda platform, uid: "Tu es amoureux." if uid == MALEF_DISCORD_ID else None
    )
    await _wally_respond(state, f"discord:{MALEF_DISCORD_ID}", "Malef", "Salut Wally")
    kwargs = state.prompts.build_system_prompt.call_args.kwargs
    assert kwargs["user_directive"] == "Tu es amoureux."
    # PIÈGE double-prefixe : l'ID brut doit être passé, jamais "discord:{id}".
    state.persona.user_directive.assert_called_once_with("discord", MALEF_DISCORD_ID)


@pytest.mark.asyncio
async def test_wally_respond_no_user_directive_for_other_user():
    state = make_state()
    state.persona.user_directive = MagicMock(
        side_effect=lambda platform, uid: "Tu es amoureux." if uid == MALEF_DISCORD_ID else None
    )
    await _wally_respond(state, "discord:99999999999999", "SomeoneElse", "Salut Wally")
    kwargs = state.prompts.build_system_prompt.call_args.kwargs
    assert kwargs["user_directive"] is None
