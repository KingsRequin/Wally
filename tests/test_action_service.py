"""Tests for ActionService — LLM facade, tool definitions, validation."""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from bot.core.actions.service import ActionService

TZ = ZoneInfo("Europe/Paris")


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.check_permission = MagicMock(return_value=True)
    reg.list_available = MagicMock(return_value=[])
    return reg


@pytest.fixture
def mock_scheduler():
    sched = AsyncMock()
    sched.schedule = AsyncMock(return_value=1)
    sched.cancel = AsyncMock()
    return sched


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.count_user_action_tasks = AsyncMock(return_value=0)
    db.search_action_tasks = AsyncMock(return_value=[])
    db.list_action_tasks = AsyncMock(return_value=[])
    db.get_action_task = AsyncMock(return_value=None)
    return db


@pytest.fixture
def service(mock_registry, mock_scheduler, mock_db):
    return ActionService(mock_registry, mock_scheduler, mock_db)


def test_get_tool_definitions(service):
    tools = service.get_tool_definitions()
    assert len(tools) == 3
    names = {t["function"]["name"] for t in tools}
    assert names == {"create_action_task", "cancel_action_task", "list_action_tasks"}


@pytest.mark.asyncio
async def test_create_task_success(service, mock_scheduler):
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "Buy bread",
            "payload": {"message": "Buy bread!"},
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "created"
    assert result["task_id"] == 1


@pytest.mark.asyncio
async def test_create_task_missing_schedule(service):
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "Buy bread",
            "payload": {"message": "Buy bread!"},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "need_more_info"
    assert "schedule" in str(result["missing"])


@pytest.mark.asyncio
async def test_create_task_permission_denied(service, mock_registry):
    mock_registry.check_permission = MagicMock(return_value=False)
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "denied"


@pytest.mark.asyncio
async def test_create_task_rate_limited(service, mock_db):
    mock_db.count_user_action_tasks = AsyncMock(return_value=10)
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": run_at},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "rate_limited"


@pytest.mark.asyncio
async def test_create_task_past_run_at_rejected(service):
    past = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "once", "run_at": past},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "error"
    assert "past" in result["message"].lower() or "passé" in result["message"].lower()


@pytest.mark.asyncio
async def test_create_task_interval_too_short(service):
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "schedule": {"type": "interval", "interval_minutes": 2},
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_cancel_by_id(service, mock_scheduler, mock_db):
    mock_db.get_action_task = AsyncMock(return_value={
        "id": 1, "description": "test", "creator_id": "123",
        "creator_platform": "discord", "status": "active",
    })
    result = await service.cancel(
        task_id=1, user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "cancelled"
    mock_scheduler.cancel.assert_called_with(1)


@pytest.mark.asyncio
async def test_cancel_by_search_single_match(service, mock_scheduler, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[
        {"id": 42, "description": "Rappel pain", "status": "active",
         "creator_id": "123", "creator_platform": "discord"}
    ])
    result = await service.cancel(
        search_query="pain", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_by_search_ambiguous(service, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[
        {"id": 1, "description": "Rappel pain", "status": "active",
         "creator_id": "123", "creator_platform": "discord"},
        {"id": 2, "description": "Rappel pain de mie", "status": "active",
         "creator_id": "123", "creator_platform": "discord"},
    ])
    result = await service.cancel(
        search_query="pain", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_cancel_by_search_not_found(service, mock_db):
    mock_db.search_action_tasks = AsyncMock(return_value=[])
    result = await service.cancel(
        search_query="inexistant", user_id="123", platform="discord", user_roles=["everyone"]
    )
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_list_tasks(service, mock_db):
    mock_db.list_action_tasks = AsyncMock(return_value=[
        {"id": 1, "action_type": "reminder", "description": "test",
         "status": "active", "next_run_at": "2026-03-23T18:00:00",
         "execution_count": 0, "max_executions": 1},
    ])
    result = await service.list_tasks(user_id="123", platform="discord")
    assert result["status"] == "ok"
    assert len(result["tasks"]) == 1


@pytest.mark.asyncio
async def test_execute_tool_routing(service):
    service.create = AsyncMock(return_value={"status": "created", "task_id": 1})
    result = await service.execute_tool(
        "create_action_task",
        {"action_type": "reminder", "description": "test",
         "schedule": {"type": "once", "run_at": "2026-12-01T10:00:00"}},
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="456",
    )
    assert result["status"] == "created"


@pytest.mark.asyncio
async def test_create_task_defaults_target_to_origin(service, mock_scheduler):
    """When target is omitted, it should default to the originating channel."""
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    result = await service.create(
        task_data={
            "action_type": "reminder",
            "description": "test",
            "payload": {"message": "hello"},
            "schedule": {"type": "once", "run_at": run_at},
            # No target specified
        },
        user_id="123", platform="discord", user_roles=["everyone"],
        channel_id="789",
    )
    assert result["status"] == "created"
    # Verify scheduler was called with the default channel
    call_kwargs = mock_scheduler.schedule.call_args[1]
    assert call_kwargs["target_channel"] == "789"
    assert call_kwargs["target_platform"] == "discord"
