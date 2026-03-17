# tests/test_sessions.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.sessions import SessionManager, _Session


def make_manager():
    memory = MagicMock()
    memory.add = AsyncMock()
    openai = MagicMock()
    openai.complete_secondary = AsyncMock(return_value="### Alice\n- aime Python")
    return SessionManager(memory=memory, openai=openai)


def make_session(n_messages=2):
    s = _Session(channel_id="ch1", platform="discord")
    for i in range(n_messages):
        s.messages.append({
            "author": "Alice", "user_id": "discord:111",
            "content": f"message {i}", "timestamp": 1000.0 + i,
        })
    s.participants["discord:111"] = "Alice"
    return s


@pytest.mark.asyncio
async def test_analyze_session_returns_int():
    mgr = make_manager()
    session = make_session()
    result = await mgr._analyze_session(session)
    assert isinstance(result, int)
    assert result == 1  # 1 participant avec faits extraits


@pytest.mark.asyncio
async def test_analyze_session_returns_zero_on_llm_error():
    mgr = make_manager()
    mgr._openai.complete_secondary = AsyncMock(side_effect=Exception("LLM down"))
    session = make_session()
    result = await mgr._analyze_session(session)
    assert result == 0  # erreur absorbée, retourne 0
