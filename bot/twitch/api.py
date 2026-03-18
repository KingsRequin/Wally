# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import httpx
from loguru import logger

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager


class TwitchAPI:
    MESSAGES_URL = "https://api.twitch.tv/helix/chat/messages"
    STREAMS_URL = "https://api.twitch.tv/helix/streams"
    USERS_URL = "https://api.twitch.tv/helix/users"

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

    async def send_message(self, text: str, broadcaster_id: Optional[str] = None) -> None:
        """POST /helix/chat/messages. Retry once on 401 after bot token refresh.

        broadcaster_id: chaîne cible. Si None, utilise self._broadcaster_id (chaîne home).
        """
        target = broadcaster_id or self._broadcaster_id
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
                            "broadcaster_id": target,
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

    async def get_broadcaster_id(self, login: str) -> Optional[str]:
        """GET /helix/users?login={login}. Retourne l'ID ou None si introuvable.

        Retry une fois sur 401. Retourne None si la chaîne n'existe pas ou si
        l'API est indisponible.
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.USERS_URL,
                        params={"login": login.lower()},
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Twitch users API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                return None
                            continue
                        return None
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    return data[0]["id"] if data else None
        except Exception as exc:
            logger.warning("get_broadcaster_id failed for {login}: {e}", login=login, e=exc)
            return None

    async def get_streams_status(self, broadcaster_ids: list[str]) -> dict[str, bool]:
        """GET /helix/streams?user_id=id1&user_id=id2...

        Retourne {broadcaster_id: is_live}. Retourne {} si la liste est vide ou en cas
        d'erreur (pas de faux positif de suppression).
        """
        if not broadcaster_ids:
            return {}
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.STREAMS_URL,
                        params=[("user_id", bid) for bid in broadcaster_ids],
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                return {}
                            continue
                        return {}
                    resp.raise_for_status()
                    live_ids = {s["user_id"] for s in resp.json().get("data", [])}
                    return {bid: (bid in live_ids) for bid in broadcaster_ids}
        except Exception as exc:
            logger.warning("get_streams_status failed: {e}", e=exc)
            return {}

    async def get_stream(self) -> dict:
        """GET /helix/streams?user_id={self._broadcaster_id}.

        Retourne un dict normalisé :
          {live, title, category, viewers, started_at}
        En cas d'erreur ou de stream offline, live=False et les autres champs sont None/0.
        Utilise self._tm.bot_token (cohérent avec send_message).
        """
        try:
            async with httpx.AsyncClient() as client:
                for attempt in range(2):
                    resp = await client.get(
                        self.STREAMS_URL,
                        params={"user_id": self._broadcaster_id},
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401:
                        if attempt == 0:
                            logger.warning(
                                "Twitch streams API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                logger.error(
                                    "Bot token refresh failed, cannot fetch stream status"
                                )
                                break
                            continue
                        logger.error("Twitch streams API 401 after refresh, giving up")
                        break
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
