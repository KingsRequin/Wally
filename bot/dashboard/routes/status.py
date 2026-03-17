# bot/dashboard/routes/status.py
from __future__ import annotations

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
    }
