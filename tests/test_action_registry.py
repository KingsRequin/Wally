"""Tests for ActionRegistry — action catalog and role-based permissions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.actions.registry import ActionRegistry, ActionDefinition


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_action_permissions = AsyncMock(return_value=[])
    db.upsert_action_permission = AsyncMock()
    db.get_action_permission = AsyncMock(return_value=None)
    return db


def _make_definition(name: str = "reminder", desc: str = "Send a reminder") -> ActionDefinition:
    return ActionDefinition(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        handler=AsyncMock(return_value="done"),
    )


@pytest.mark.asyncio
async def test_register_and_get(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    defn = _make_definition()
    await reg.register("reminder", defn)
    assert reg.get("reminder") is defn
    assert reg.get("nonexistent") is None


@pytest.mark.asyncio
async def test_register_creates_default_permission(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    mock_db.upsert_action_permission.assert_called_once_with(
        "reminder", min_role_discord="admin", min_role_twitch="admin", enabled=1
    )


@pytest.mark.asyncio
async def test_check_permission_discord_hierarchy(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "moderator", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["admin"]) is True
    assert reg.check_permission("reminder", "discord", ["moderator"]) is True
    assert reg.check_permission("reminder", "discord", ["subscriber"]) is False
    assert reg.check_permission("reminder", "discord", ["everyone"]) is False


@pytest.mark.asyncio
async def test_check_permission_twitch_hierarchy(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "vip", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "twitch", ["moderator"]) is True
    assert reg.check_permission("reminder", "twitch", ["vip"]) is True
    assert reg.check_permission("reminder", "twitch", ["subscriber"]) is False


@pytest.mark.asyncio
async def test_check_permission_disabled_action(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "everyone", "enabled": 0}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["admin"]) is False


@pytest.mark.asyncio
async def test_check_permission_unknown_action(mock_db):
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    assert reg.check_permission("nonexistent", "discord", ["admin"]) is False


@pytest.mark.asyncio
async def test_list_available(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "admin", "enabled": 1},
        {"action_type": "web_search", "min_role_discord": "moderator", "min_role_twitch": "admin", "enabled": 1},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition("reminder"))
    await reg.register("web_search", _make_definition("web_search", "Search the web"))
    available = reg.list_available("discord", ["subscriber"])
    assert len(available) == 1
    assert available[0].name == "reminder"
    available_mod = reg.list_available("discord", ["moderator"])
    assert len(available_mod) == 2


@pytest.mark.asyncio
async def test_update_permission(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "admin", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    await reg.update_permission("reminder", "discord", "everyone")
    assert reg.check_permission("reminder", "discord", ["everyone"]) is True


@pytest.mark.asyncio
async def test_set_enabled(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_discord": "everyone", "min_role_twitch": "everyone", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["everyone"]) is True
    await reg.set_enabled("reminder", False)
    assert reg.check_permission("reminder", "discord", ["everyone"]) is False
