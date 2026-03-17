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


def make_discord_message(
    author_id=111,
    display_name="Alice",
    is_bot=False,
    content="Bonjour",
    timestamp=1000.0,
):
    msg = MagicMock()
    msg.author.id = author_id
    msg.author.display_name = display_name
    msg.author.bot = is_bot
    msg.content = content
    msg.created_at.timestamp.return_value = timestamp
    return msg


BOT_USER_ID = 999  # ID fictif de Wally dans les tests


@pytest.mark.asyncio
async def test_analyze_channel_messages_returns_stored_count():
    """Cas nominal : 2 messages humains → analyse → 1 participant stocké."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="Salut", timestamp=1000.0),
        make_discord_message(author_id=222, display_name="Bob", content="Hey", timestamp=1001.0),
    ]
    result = await mgr.analyze_channel_messages(
        messages=msgs, platform="discord", channel_id="ch1", bot_user_id=BOT_USER_ID
    )
    assert isinstance(result, int)
    assert result == 1  # Alice a des faits, Bob n'a pas de section dans l'analyse mock


@pytest.mark.asyncio
async def test_analyze_channel_messages_excludes_other_bots():
    """Les messages de bots tiers sont exclus."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="Salut", timestamp=1000.0),
        make_discord_message(author_id=777, display_name="OtherBot", is_bot=True, content="beep", timestamp=1001.0),
        make_discord_message(author_id=222, display_name="Bob", content="Hey", timestamp=1002.0),
    ]
    # OtherBot doit être exclu — les 2 messages humains suffisent pour l'analyse
    result = await mgr.analyze_channel_messages(
        messages=msgs, platform="discord", channel_id="ch1", bot_user_id=BOT_USER_ID
    )
    # Vérifier que complete_secondary a bien été appelé (analyse lancée)
    mgr._openai.complete_secondary.assert_called_once()
    conv_arg = mgr._openai.complete_secondary.call_args[0][1][0]["content"]
    assert "OtherBot" not in conv_arg
    assert "Alice" in conv_arg
    assert "Bob" in conv_arg


@pytest.mark.asyncio
async def test_analyze_channel_messages_wally_included_as_context_not_participant():
    """Wally est inclus dans le contexte mais absent des participants."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="Salut", timestamp=1000.0),
        make_discord_message(author_id=BOT_USER_ID, display_name="Wally", is_bot=True, content="Bonjour!", timestamp=1001.0),
        make_discord_message(author_id=222, display_name="Bob", content="Hey", timestamp=1002.0),
    ]
    # Patch _analyze_session pour capturer la session construite
    captured = {}

    async def fake_analyze(session):
        captured["session"] = session
        return 0

    mgr._analyze_session = fake_analyze
    await mgr.analyze_channel_messages(
        messages=msgs, platform="discord", channel_id="ch1", bot_user_id=BOT_USER_ID
    )
    session = captured["session"]
    # Wally dans messages mais pas dans participants
    authors_in_msgs = [m["author"] for m in session.messages]
    assert "Wally" in authors_in_msgs
    assert str(BOT_USER_ID) not in session.participants


@pytest.mark.asyncio
async def test_analyze_channel_messages_excludes_empty_content():
    """Les messages vides sont exclus."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="   ", timestamp=1000.0),
        make_discord_message(author_id=222, display_name="Bob", content="", timestamp=1001.0),
    ]
    with pytest.raises(ValueError):
        await mgr.analyze_channel_messages(
            messages=msgs, platform="discord", channel_id="ch1", bot_user_id=BOT_USER_ID
        )


@pytest.mark.asyncio
async def test_analyze_channel_messages_raises_if_too_few_humans():
    """ValueError si moins de 2 messages humains."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="Salut", timestamp=1000.0),
    ]
    with pytest.raises(ValueError):
        await mgr.analyze_channel_messages(
            messages=msgs, platform="discord", channel_id="ch1", bot_user_id=BOT_USER_ID
        )


@pytest.mark.asyncio
async def test_analyze_channel_messages_session_fields():
    """timeout_task=None, last_activity = timestamp du dernier message."""
    mgr = make_manager()
    msgs = [
        make_discord_message(author_id=111, display_name="Alice", content="Salut", timestamp=1000.0),
        make_discord_message(author_id=222, display_name="Bob", content="Hey", timestamp=1500.0),
    ]
    captured = {}

    async def fake_analyze(session):
        captured["session"] = session
        return 0

    mgr._analyze_session = fake_analyze
    await mgr.analyze_channel_messages(
        messages=msgs, platform="discord", channel_id="ch42", bot_user_id=BOT_USER_ID
    )
    session = captured["session"]
    assert session.timeout_task is None
    assert session.last_activity == 1500.0
    assert session.channel_id == "ch42"
    assert session.platform == "discord"
