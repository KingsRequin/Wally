"""Tests for ActionRegistry — action catalog and role-based permissions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.actions.registry import ActionRegistry, ActionDefinition


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_action_permissions = AsyncMock(return_value=[])
    db.list_discord_permissions = AsyncMock(return_value=[])
    db.upsert_action_permission = AsyncMock()
    db.get_action_permission = AsyncMock(return_value=None)
    db.set_discord_permissions = AsyncMock()
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
async def test_discord_permission_matching_role_granted(mock_db):
    """User with a role_id that is in the allowed set → granted."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "R100", "role_name": "Mods"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["R100"], guild_id="G1") is True


@pytest.mark.asyncio
async def test_discord_permission_no_matching_role_denied(mock_db):
    """User without a matching role_id → denied."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "R100", "role_name": "Mods"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["R999"], guild_id="G1") is False


@pytest.mark.asyncio
async def test_discord_permission_admin_always_granted(mock_db):
    """Admin role always passes regardless of guild config."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    # No discord_perms rows at all, but admin still passes
    assert reg.check_permission("reminder", "discord", ["admin"], guild_id="G1") is True
    assert reg.check_permission("reminder", "discord", ["admin"], guild_id=None) is True


@pytest.mark.asyncio
async def test_discord_permission_everyone_grants_all(mock_db):
    """'everyone' in allowed roles → grants all users in that guild."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "everyone", "role_name": "@everyone"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["R_ANY"], guild_id="G1") is True


@pytest.mark.asyncio
async def test_discord_permission_no_guild_denied(mock_db):
    """No guild_id (DMs) → denied unless admin."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "R100", "role_name": "Mods"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["R100"], guild_id=None) is False


@pytest.mark.asyncio
async def test_discord_permission_no_rows_for_guild_denied(mock_db):
    """No discord_perms rows for this guild → denied unless admin."""
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "R100", "role_name": "Mods"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    # Different guild → no rows
    assert reg.check_permission("reminder", "discord", ["R100"], guild_id="G_OTHER") is False


@pytest.mark.asyncio
async def test_check_permission_twitch_hierarchy(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "vip", "enabled": 1}
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
        {"action_type": "reminder", "min_role_twitch": "everyone", "enabled": 0}
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
async def test_list_available_discord_with_guild(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1},
        {"action_type": "web_search", "min_role_twitch": "admin", "enabled": 1},
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "everyone", "role_name": "@everyone"},
        {"action_type": "web_search", "guild_id": "G1", "role_id": "R_MOD", "role_name": "Mods"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition("reminder"))
    await reg.register("web_search", _make_definition("web_search", "Search the web"))
    # Regular user only sees reminder (everyone), not web_search
    available = reg.list_available("discord", ["R_SUB"], guild_id="G1")
    assert len(available) == 1
    assert available[0].name == "reminder"
    # User with R_MOD sees both
    available_mod = reg.list_available("discord", ["R_MOD"], guild_id="G1")
    assert len(available_mod) == 2


@pytest.mark.asyncio
async def test_update_permission_twitch(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    await reg.update_permission("reminder", "twitch", "everyone")
    assert reg.check_permission("reminder", "twitch", ["everyone"]) is True


@pytest.mark.asyncio
async def test_update_discord_permission(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "admin", "enabled": 1}
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    # Initially no discord perms → denied
    assert reg.check_permission("reminder", "discord", ["R200"], guild_id="G1") is False
    # Add via update_discord_permission
    await reg.update_discord_permission("reminder", "G1", [
        {"role_id": "R200", "role_name": "Subs"},
    ])
    assert reg.check_permission("reminder", "discord", ["R200"], guild_id="G1") is True
    mock_db.set_discord_permissions.assert_called_once()


@pytest.mark.asyncio
async def test_set_enabled(mock_db):
    mock_db.list_action_permissions.return_value = [
        {"action_type": "reminder", "min_role_twitch": "everyone", "enabled": 1}
    ]
    mock_db.list_discord_permissions.return_value = [
        {"action_type": "reminder", "guild_id": "G1", "role_id": "everyone", "role_name": "@everyone"},
    ]
    reg = ActionRegistry(mock_db)
    await reg.load_permissions()
    await reg.register("reminder", _make_definition())
    assert reg.check_permission("reminder", "discord", ["anyone"], guild_id="G1") is True
    await reg.set_enabled("reminder", False)
    assert reg.check_permission("reminder", "discord", ["anyone"], guild_id="G1") is False
