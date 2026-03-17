import pytest
from unittest.mock import MagicMock, AsyncMock

from bot.core.sessions import SessionManager, _Session


@pytest.mark.asyncio
async def test_analyze_session_passes_display_name_as_username():
    """_analyze_session doit passer display_name comme username à memory.add()."""
    mock_memory = MagicMock()
    mock_memory.add = AsyncMock()

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(
        return_value="### OlafMC\n- aime le jeu de stratégie\n"
    )

    manager = SessionManager(mock_memory, mock_openai)

    session = _Session(
        channel_id="ch1",
        platform="discord",
        messages=[
            {"author": "OlafMC", "user_id": "111", "content": "salut", "timestamp": 1.0},
            {"author": "OlafMC", "user_id": "111", "content": "tu joues ?", "timestamp": 2.0},
        ],
        participants={"111": "OlafMC"},
    )

    await manager._analyze_session(session)

    mock_memory.add.assert_called_once()
    call_kwargs = mock_memory.add.call_args.kwargs
    assert call_kwargs.get("username") == "OlafMC"
