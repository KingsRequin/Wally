# tests/test_apex_api.py
"""Tests for ApexLegendsService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.apex_api import ApexLegendsService, APEX_LEGENDS_TOOL


# ── Tool definition ──────────────────────────────────────────────────────────


def test_tool_definition_structure():
    tool = APEX_LEGENDS_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "apex_legends"
    params = tool["function"]["parameters"]
    assert "action" in params["properties"]
    assert "player_name" in params["properties"]
    assert "platform" in params["properties"]
    assert params["properties"]["action"]["enum"] == [
        "player_stats", "map_rotation", "crafting", "news", "predator", "server_status",
    ]


def test_available_without_key():
    with patch.dict("os.environ", {"APEX_API_KEY": ""}, clear=False):
        service = ApexLegendsService()
    assert service.available is False


def test_available_with_key():
    with patch.dict("os.environ", {"APEX_API_KEY": "test-key"}, clear=False):
        service = ApexLegendsService()
    assert service.available is True


# ── Player stats ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_player_stats_formats_correctly():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = {
        "global": {
            "name": "TestPlayer",
            "level": 500,
            "platform": "PC",
            "rank": {"rankName": "Diamond", "rankDiv": "2", "rankScore": 8400},
            "arena": {"rankName": "Platinum", "rankDiv": "1", "rankScore": 5200},
        },
        "legends": {
            "selected": {
                "LegendName": "Wraith",
                "data": [
                    {"name": "Kills", "value": 15000},
                    {"name": "Damage", "value": 3500000},
                ],
            }
        },
    }

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("player_stats", player_name="TestPlayer", platform="PC")

    assert "TestPlayer" in result
    assert "Diamond" in result
    assert "Wraith" in result
    assert "15000" in result


@pytest.mark.asyncio
async def test_player_stats_requires_name():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    result = await service.execute("player_stats", player_name="", platform="PC")
    assert "required" in result.lower()


# ── Map rotation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_map_rotation_formats():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = {
        "battle_royale": {
            "current": {"map": "World's Edge", "remainingTimer": "45:32"},
            "next": {"map": "Storm Point"},
        },
        "ranked": {
            "current": {"map": "Olympus", "remainingTimer": "1:23:45"},
            "next": {"map": "Kings Canyon"},
        },
    }

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("map_rotation")

    assert "World's Edge" in result
    assert "Olympus" in result
    assert "Storm Point" in result


# ── Crafting ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crafting_formats():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = [
        {
            "bundleType": "daily",
            "bundleContent": [
                {"itemType": {"name": "Barrel Stabilizer"}},
                {"itemType": {"name": "Shotgun Bolt"}},
            ],
        }
    ]

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("crafting")

    assert "Barrel Stabilizer" in result
    assert "daily" in result


# ── Predator ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_predator_formats():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = {
        "RP": {"PC": {"val": 18500, "totalMastersAndPreds": 750}},
        "AP": {"PC": {"val": 12000, "totalMastersAndPreds": 300}},
    }

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("predator")

    assert "18500" in result
    assert "750" in result


# ── Server status ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_server_status_formats():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = {
        "EA_novafusion": {
            "EU-West": {"Status": "UP"},
            "US-East": {"Status": "DOWN"},
        }
    }

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("server_status")

    assert "✅" in result
    assert "❌" in result
    assert "EU-West" in result


# ── News ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_news_formats():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    mock_data = [
        {"title": "Season 22 Update", "short_desc": "New legend!", "link": "https://example.com"},
    ]

    with patch.object(service, "_get", new=AsyncMock(return_value=mock_data)):
        result = await service.execute("news")

    assert "Season 22" in result
    assert "New legend!" in result


# ── Error handling ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_error_returns_string():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    with patch.object(service, "_get", new=AsyncMock(return_value="Apex API error (HTTP 500)")):
        result = await service.execute("map_rotation")

    assert "error" in result.lower()


@pytest.mark.asyncio
async def test_unknown_action():
    with patch.dict("os.environ", {"APEX_API_KEY": "test"}, clear=False):
        service = ApexLegendsService()

    result = await service.execute("invalid_action")
    assert "Unknown" in result


# ── Discord handler integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_handler_adds_gun_reaction_on_apex():
    from bot.discord.handlers import _respond

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.get_love_score = AsyncMock(return_value=0.0)
    bot.db.update_trust_score = AsyncMock()
    bot.db.update_love_score = AsyncMock()
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.config.bot.love_decay_lambda = 0.02
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.search_global = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.memory.get_pending_question_directive = AsyncMock(return_value="")
    bot.db.get_last_interaction = AsyncMock(return_value=None)
    bot.db.get_recent_jokes = AsyncMock(return_value=[])
    bot.db.get_opinions = AsyncMock(return_value=[])
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.0})
    bot.emotion.process_message = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()

    # No web search
    bot.web_search = None
    bot.scrape = None

    # Apex API mock
    apex_api = MagicMock()
    apex_api.available = True
    apex_api.get_tool_definition = MagicMock(return_value=APEX_LEGENDS_TOOL)
    apex_api.execute = AsyncMock(return_value="Diamond 2, 8400 RP")
    bot.apex_api = apex_api

    bot.llm.complete_with_tools = AsyncMock(return_value=("Il est Diamond 2", ["apex_legends"]))

    msg = MagicMock()
    msg.content = "wally c'est quoi le rank de Daltoosh"
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = []

    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, msg, "12345", "99999", [])

    # complete_with_tools called with apex tool
    bot.llm.complete_with_tools.assert_awaited_once()
    call_args = bot.llm.complete_with_tools.call_args
    tools_passed = call_args.args[2]
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "apex_legends" in tool_names
    # Response sent
    msg.reply.assert_awaited_once()
