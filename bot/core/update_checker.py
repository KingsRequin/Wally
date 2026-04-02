# bot/core/update_checker.py
from __future__ import annotations

import asyncio
import os
import subprocess

import httpx
from loguru import logger


class UpdateChecker:
    """Vérifie périodiquement si une nouvelle image est disponible sur GHCR.

    Usage :
        checker = UpdateChecker("ghcr.io/user/wally-ai:latest")
        checker.start()           # démarre la boucle asyncio
        checker.update_available  # True si mise à jour détectée
        checker.update_available = False  # reset après déclenchement
        await checker.stop()
    """

    def __init__(self, image_ref: str, check_interval_seconds: int = 3600) -> None:
        self._image_ref = image_ref
        self._interval = check_interval_seconds
        self._update_available: bool = False
        self._task: asyncio.Task | None = None

    @property
    def update_available(self) -> bool:
        return self._update_available

    @update_available.setter
    def update_available(self, value: bool) -> None:
        self._update_available = value

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("UpdateChecker started — image={} interval={}s", self._image_ref, self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await self._check()
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        try:
            current = await self._running_digest()
            if not current:
                return  # image locale sans RepoDigest — skip
            remote = await self._remote_digest()
            if remote and current != remote:
                if not self._update_available:
                    logger.info("Update available: {} → {}", current[:19], remote[:19])
                self._update_available = True
            elif remote:
                self._update_available = False
        except Exception as exc:
            logger.warning("UpdateChecker: check failed: {}", exc)

    async def _running_digest(self) -> str | None:
        """Retourne le digest manifest de l'image courante (RepoDigests via docker inspect)."""
        container_id = os.environ.get("HOSTNAME", "")
        if not container_id:
            return None
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["/usr/bin/docker", "inspect", "--format", "{{index .RepoDigests 0}}", container_id],
                capture_output=True, text=True, timeout=5,
            )
            raw = result.stdout.strip()
            if not raw or "@" not in raw:
                return None
            return raw.split("@", 1)[1]  # sha256:abc123...
        except Exception as exc:
            logger.warning("UpdateChecker: docker inspect failed: {}", exc)
            return None

    async def _remote_digest(self) -> str | None:
        """Retourne le digest manifest de la dernière image sur GHCR (sans auth pour images publiques)."""
        ref = self._image_ref
        if ref.startswith("ghcr.io/"):
            ref = ref[8:]
        name, tag = (ref.rsplit(":", 1) if ":" in ref else (ref, "latest"))

        manifest_url = f"https://ghcr.io/v2/{name}/manifests/{tag}"
        accept = "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(manifest_url, headers={"Accept": accept})
                if r.status_code == 401:
                    token_url = f"https://ghcr.io/token?scope=repository:{name}:pull&service=ghcr.io"
                    tr = await client.get(token_url)
                    if tr.status_code != 200:
                        return None
                    token = tr.json().get("token", "")
                    if not token:
                        logger.warning("UpdateChecker: GHCR token vide")
                        return None
                    r = await client.get(manifest_url, headers={"Accept": accept, "Authorization": f"Bearer {token}"})
                if r.status_code == 200:
                    return r.headers.get("Docker-Content-Digest")
        except Exception as exc:
            logger.warning("UpdateChecker: GHCR request failed: {}", exc)
        return None
