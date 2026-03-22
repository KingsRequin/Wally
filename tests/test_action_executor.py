"""Tests for ActionExecutor — action routing and message delivery."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock

from bot.core.actions.executor import ActionExecutor
from bot.core.actions.registry import ActionDefinition, ActionRegistry


@pytest.fixture
def mock_registry():
    reg = MagicMock(spec=ActionRegistry)
    handler = AsyncMock(return_value="Reminder sent!")
    defn = ActionDefinition(name="reminder", description="Send a reminder",
                            parameters={}, handler=handler)
    reg.get = MagicMock(return_value=defn)
    return reg


@pytest.fixture
def mock_discord_bot():
    bot = MagicMock()
    channel = AsyncMock()
    channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


@pytest.fixture
def mock_twitch_bot():
    bot = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=channel)
    return bot


@pytest.fixture
def executor(mock_registry):
    return ActionExecutor(mock_registry)


@pytest.mark.asyncio
async def test_execute_calls_handler(executor, mock_registry):
    executor.set_bots(MagicMock(), MagicMock())
    task = {"id": 1, "action_type": "reminder", "payload": '{"message": "Buy bread"}',
            "target_platform": "discord", "target_channel": "123",
            "creator_id": "456", "creator_platform": "discord"}
    result = await executor.execute(task)
    assert result == "Reminder sent!"
    mock_registry.get.assert_called_with("reminder")


@pytest.mark.asyncio
async def test_execute_unknown_action(executor):
    executor.set_bots(MagicMock(), MagicMock())
    executor._registry.get = MagicMock(return_value=None)
    task = {"id": 1, "action_type": "unknown", "payload": '{}',
            "target_platform": "discord", "target_channel": "123",
            "creator_id": "456", "creator_platform": "discord"}
    result = await executor.execute(task)
    assert "Unknown action" in result


@pytest.mark.asyncio
async def test_execute_without_bots_returns_error(executor):
    task = {"id": 1, "action_type": "reminder", "payload": '{"message": "test"}',
            "target_platform": "discord", "target_channel": "123",
            "creator_id": "456", "creator_platform": "discord"}
    result = await executor.execute(task)
    assert "not" in result.lower()


@pytest.mark.asyncio
async def test_deliver_discord(executor, mock_discord_bot):
    executor.set_bots(mock_discord_bot, MagicMock())
    await executor.deliver("Hello!", "discord", "123", dm=False)
    mock_discord_bot.get_channel.assert_called_with(123)


@pytest.mark.asyncio
async def test_deliver_twitch(executor, mock_twitch_bot):
    executor.set_bots(MagicMock(), mock_twitch_bot)
    await executor.deliver("Hello!", "twitch", "general", dm=False)
    mock_twitch_bot.get_channel.assert_called_with("general")


@pytest.mark.asyncio
async def test_handler_exception_propagates(executor):
    executor.set_bots(MagicMock(), MagicMock())
    handler = AsyncMock(side_effect=RuntimeError("API down"))
    defn = ActionDefinition(name="broken", description="", parameters={}, handler=handler)
    executor._registry.get = MagicMock(return_value=defn)
    task = {"id": 1, "action_type": "broken", "payload": '{}',
            "target_platform": "discord", "target_channel": "123",
            "creator_id": "456", "creator_platform": "discord"}
    with pytest.raises(RuntimeError, match="API down"):
        await executor.execute(task)
