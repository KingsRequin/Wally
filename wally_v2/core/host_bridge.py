from __future__ import annotations

import httpx
from loguru import logger


class HostBridgeError(Exception):
    pass


class HostBridgeClient:
    def __init__(self, socket_path: str, secret: str) -> None:
        self._socket_path = socket_path
        self._secret = secret

    def _transport(self) -> httpx.AsyncHTTPTransport:
        return httpx.AsyncHTTPTransport(uds=self._socket_path)

    def _headers(self) -> dict[str, str]:
        return {"X-Bridge-Secret": self._secret}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(transport=self._transport(), timeout=5.0) as c:
                r = await c.get("http://bridge/health")
                return r.status_code == 200
        except Exception as e:
            logger.warning("HostBridge health failed: {}", e)
            return False

    async def git_apply(self, diff: str) -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=30.0) as c:
            r = await c.post(
                "http://bridge/git-apply",
                json={"diff": diff},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))

    async def docker_rebuild(self, service: str = "wally") -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=10.0) as c:
            r = await c.post(
                "http://bridge/docker-rebuild",
                json={"service": service},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))

    async def docker_restart(self, service: str = "wally") -> None:
        async with httpx.AsyncClient(transport=self._transport(), timeout=10.0) as c:
            r = await c.post(
                "http://bridge/docker-restart",
                json={"service": service},
                headers=self._headers(),
            )
            if r.status_code != 200:
                raise HostBridgeError(r.json().get("error", "unknown error"))
