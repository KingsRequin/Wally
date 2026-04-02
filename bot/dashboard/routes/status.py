# bot/dashboard/routes/status.py
from __future__ import annotations

import os
import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Retourne uptime, connectivité Discord/Twitch, et compteur de messages."""
    state = request.app.state.wally

    uptime = time.time() - state.start_time

    discord_online = (
        state.discord_bot is not None
        and state.discord_bot.is_ready()
    )
    twitch_online = (
        state.twitch_bot is not None
        and getattr(state.twitch_bot, "_eventsub_client", None) is not None
    )

    return {
        "uptime_seconds": uptime,
        "discord_online": discord_online,
        "twitch_online": twitch_online,
        "total_messages": state.message_count,
        "messages_discord": state.message_count_discord,
        "messages_twitch": state.message_count_twitch,
        "messages_web": state.message_count_web,
        "git_hash": os.getenv("BOT_GIT_HASH", "unknown"),
        "build_date": os.getenv("BOT_BUILD_DATE", "unknown"),
    }
