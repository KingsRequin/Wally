# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager


class TwitchAPI:
    MESSAGES_URL = "https://api.twitch.tv/helix/chat/messages"

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
        for attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
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
                return
            except Exception as exc:
                logger.error("Twitch send_message error: {e}", e=exc)
                return
