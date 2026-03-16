# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager


class TwitchAPI:
    MESSAGES_URL = "https://api.twitch.tv/helix/chat/messages"
    STREAMS_URL = "https://api.twitch.tv/helix/streams"

    def __init__(
        self,
        token_manager: "TwitchTokenManager",
        client_id: str,
        bot_id: str,
        broadcaster_id: str,
    ):
        self._tm = token_manager
        self._client_id = client_id
        self._bot_id = bot_id
        self._broadcaster_id = broadcaster_id

    async def send_message(self, text: str) -> None:
        """POST /helix/chat/messages. Retry once on 401 after bot token refresh."""
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.post(
                        self.MESSAGES_URL,
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        json={
                            "broadcaster_id": self._broadcaster_id,
                            "sender_id": self._bot_id,
                            "message": text,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Twitch chat API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                logger.error(
                                    "Bot token refresh failed, cannot send message"
                                )
                                return
                            continue
                        logger.error("Twitch chat API 401 after refresh, giving up")
                        return
                    resp.raise_for_status()
                    return
        except httpx.HTTPStatusError as exc:
            logger.error("Twitch send_message HTTP error: {e}", e=exc)
        except Exception as exc:
            logger.error("Twitch send_message error: {e}", e=exc)

    async def get_stream(self) -> dict:
        """GET /helix/streams?user_id={self._broadcaster_id}.

        Retourne un dict normalisé :
          {live, title, category, viewers, started_at}
        En cas d'erreur ou de stream offline, live=False et les autres champs sont None/0.
        Utilise self._tm.bot_token (cohérent avec send_message).
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.STREAMS_URL,
                    params={"user_id": self._broadcaster_id},
                    headers={
                        "Authorization": f"Bearer {self._tm.bot_token}",
                        "Client-Id": self._client_id,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if not data:
                    return {
                        "live": False,
                        "title": None,
                        "category": None,
                        "viewers": 0,
                        "started_at": None,
                    }
                s = data[0]
                return {
                    "live": True,
                    "title": s.get("title"),
                    "category": s.get("game_name"),
                    "viewers": s.get("viewer_count", 0),
                    "started_at": s.get("started_at"),
                }
        except Exception as exc:
            logger.warning("Failed to fetch Twitch stream status: {e}", e=exc)
            return {
                "live": False,
                "title": None,
                "category": None,
                "viewers": 0,
                "started_at": None,
            }
