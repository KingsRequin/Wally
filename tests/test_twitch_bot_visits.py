# tests/test_twitch_bot_visits.py
"""Tests pour le tracking des visites Twitch invitées dans WallyTwitch."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_twitch_bot():
    """Retourne un WallyTwitch minimal mocké pour les tests de visite."""
    from bot.twitch.bot import WallyTwitch
    # On bypasse __init__ de twitchio
    bot = object.__new__(WallyTwitch)
    bot.config = MagicMock()
    bot.config.twitch.channel = "homechannel"
    bot.config.twitch.guest_channels = []
    bot.db = MagicMock()
    bot.db.start_twitch_visit = AsyncMock(return_value=42)
    bot.db.end_twitch_visit = AsyncMock()
    bot.memory = MagicMock()
    bot.memory.get_context = MagicMock(return_value=[
        {"author": "viewer1", "content": "poggers", "timestamp": time.time()},
        {"author": "viewer2", "content": "hype train!", "timestamp": time.time() + 1},
    ])
    bot.llm_secondary = MagicMock()
    bot.llm_secondary.complete = AsyncMock(return_value="Bonne visite chez streamer.")
    bot._cooldowns = {}
    bot._channel_ids = {}
    bot._channel_was_live = {}
    bot._active_visits = {}
    bot._bg_tasks = set()
    bot.config.save = MagicMock()
    return bot


@pytest.mark.asyncio
async def test_add_guest_channel_starts_visit(tmp_path):
    """add_guest_channel doit créer une entrée dans _active_visits."""
    bot = make_twitch_bot()
    bot.twitch_api = MagicMock()
    bot.twitch_api.get_broadcaster_id = AsyncMock(return_value="999")

    with patch.object(bot, "join_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.add_guest_channel("streamer1")

    assert "streamer1" in bot._active_visits
    info = bot._active_visits["streamer1"]
    assert info["visit_id"] == 42
    assert info["msg_count"] == 0
    assert isinstance(info["joined_at"], float)
    bot.db.start_twitch_visit.assert_awaited_once_with("streamer1")


@pytest.mark.asyncio
async def test_remove_guest_channel_finalizes_visit(tmp_path):
    """remove_guest_channel doit lancer _finalize_visit en fire-and-forget."""
    bot = make_twitch_bot()
    bot.config.twitch.guest_channels = ["streamer1"]
    bot._active_visits["streamer1"] = {
        "visit_id": 42,
        "msg_count": 5,
        "joined_at": time.time() - 300,
    }

    with patch.object(bot, "part_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.remove_guest_channel("streamer1")

    # Laisser les tâches fire-and-forget se terminer
    await asyncio.sleep(0.05)

    assert "streamer1" not in bot._active_visits
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[0] == 42   # visit_id
    assert call_args.args[2] == 5    # msg_count
    assert call_args.args[3] == "Bonne visite chez streamer."  # summary


@pytest.mark.asyncio
async def test_remove_guest_channel_without_active_visit():
    """remove_guest_channel sans visite active ne doit pas lever d'erreur."""
    bot = make_twitch_bot()
    bot.config.twitch.guest_channels = []
    # Pas d'entrée dans _active_visits

    with patch.object(bot, "part_channels", AsyncMock()), \
         patch.object(bot, "_restart_eventsub", AsyncMock()):
        await bot.remove_guest_channel("unknownchannel")  # ne doit pas raise

    bot.db.end_twitch_visit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_visit_calls_llm_and_db():
    """_finalize_visit doit appeler llm_secondary et end_twitch_visit."""
    bot = make_twitch_bot()
    joined_at = time.time() - 600

    await bot._finalize_visit("streamer1", 42, joined_at, 10)

    bot.llm_secondary.complete.assert_awaited_once()
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[0] == 42
    assert call_args.args[2] == 10  # msg_count
    assert call_args.args[3] == "Bonne visite chez streamer."


@pytest.mark.asyncio
async def test_finalize_visit_handles_llm_error():
    """_finalize_visit doit enregistrer la visite même si le LLM échoue."""
    bot = make_twitch_bot()
    bot.llm_secondary.complete = AsyncMock(side_effect=Exception("LLM timeout"))
    joined_at = time.time() - 120

    await bot._finalize_visit("streamer1", 42, joined_at, 3)

    # end_twitch_visit doit quand même être appelé avec summary=None
    bot.db.end_twitch_visit.assert_awaited_once()
    call_args = bot.db.end_twitch_visit.call_args
    assert call_args.args[3] is None
