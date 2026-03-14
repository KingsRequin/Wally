from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import httpx
from loguru import logger


class TwitchTokenManager:
    VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"

    def __init__(
        self,
        env_path: Path,
        bot_token: str,
        bot_refresh: str,
        streamer_token: str,
        streamer_refresh: str,
        client_id: str,
        client_secret: str,
    ):
        self._env_path = env_path
        self._bot_token = bot_token
        self._bot_refresh = bot_refresh
        self._streamer_token = streamer_token
        self._streamer_refresh = streamer_refresh
        self._client_id = client_id
        self._client_secret = client_secret

    @property
    def bot_token(self) -> str:
        return self._bot_token

    @property
    def streamer_token(self) -> str:
        return self._streamer_token

    @classmethod
    def load(cls, env_path: Path) -> "TwitchTokenManager":
        return cls(
            env_path=env_path,
            bot_token=os.getenv("BOT_ACCESS_TOKEN", ""),
            bot_refresh=os.getenv("BOT_REFRESH_TOKEN", ""),
            streamer_token=os.getenv("STREAMER_ACCESS_TOKEN", ""),
            streamer_refresh=os.getenv("STREAMER_REFRESH_TOKEN", ""),
            client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
        )

    async def startup_validate(self) -> None:
        for token_type in ("bot", "streamer"):
            token = self._bot_token if token_type == "bot" else self._streamer_token
            if not token:
                logger.warning("Twitch {t} token not set", t=token_type)
                continue
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        self.VALIDATE_URL,
                        headers={"Authorization": f"OAuth {token}"},
                        timeout=10,
                    )
                if resp.status_code == 401:
                    logger.warning(
                        "Twitch {t} token invalid at startup, refreshing...", t=token_type
                    )
                    await self.refresh(token_type)
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    logger.info(
                        "Twitch {t} token valid — scopes={scopes} expires_in={exp}s",
                        t=token_type,
                        scopes=data.get("scopes", []),
                        exp=data.get("expires_in", "?"),
                    )
            except Exception as exc:
                logger.error(
                    "Twitch {t} token validation error: {e}", t=token_type, e=exc
                )

    async def refresh(self, token_type: Literal["bot", "streamer"]) -> bool:
        refresh_token = (
            self._bot_refresh if token_type == "bot" else self._streamer_refresh
        )
        if not refresh_token:
            logger.error(
                "Cannot refresh Twitch {t} token — refresh token not set", t=token_type
            )
            return False
        if not self._client_id or not self._client_secret:
            logger.error(
                "Cannot refresh Twitch {t} token — CLIENT_ID/SECRET not set",
                t=token_type,
            )
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
            new_token: str = data["access_token"]
            new_refresh: str = data["refresh_token"]
            if token_type == "bot":
                self._bot_token = new_token
                self._bot_refresh = new_refresh
            else:
                self._streamer_token = new_token
                self._streamer_refresh = new_refresh
            self._write_env(token_type, new_token, new_refresh)
            logger.info("Twitch {t} token refreshed successfully", t=token_type)
            return True
        except Exception as exc:
            logger.error(
                "Twitch {t} token refresh failed: {e}", t=token_type, e=exc
            )
            return False

    def _write_env(
        self,
        token_type: Literal["bot", "streamer"],
        new_token: str,
        new_refresh: str,
    ) -> None:
        if not self._env_path.exists():
            logger.warning(
                ".env not found at {p}, skipping persistence", p=self._env_path
            )
            return
        if token_type == "bot":
            access_key, refresh_key = "BOT_ACCESS_TOKEN", "BOT_REFRESH_TOKEN"
        else:
            access_key, refresh_key = "STREAMER_ACCESS_TOKEN", "STREAMER_REFRESH_TOKEN"
        content = self._env_path.read_text(encoding="utf-8")

        def _replace_or_append(text: str, key: str, value: str) -> str:
            pattern = rf"^{key}=.*$"
            if re.search(pattern, text, flags=re.MULTILINE):
                return re.sub(pattern, f"{key}={value}", text, flags=re.MULTILINE)
            return text.rstrip("\n") + f"\n{key}={value}\n"

        content = _replace_or_append(content, access_key, new_token)
        content = _replace_or_append(content, refresh_key, new_refresh)
        tmp_path = self._env_path.parent / ".env.tmp"
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(self._env_path))
