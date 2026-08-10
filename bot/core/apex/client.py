# bot/core/apex/client.py
"""Accès réseau à l'API Apex Legends Status : débit borné, réponses en cache.

Un seul objet parle au réseau dans tout le paquet. Le cache évite qu'une même
question posée deux fois en dix secondes coûte deux appels — la rotation des
cartes ne change pas plus vite que la minute.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger

_BASE_URL = "https://api.mozambiquehe.re"

# Durée de validité par endpoint, en secondes. Choisies sur ce que la donnée
# représente : les lots du replicator tiennent la journée, l'état d'un joueur
# non.
DEFAULT_TTL: dict[str, float] = {
    "maprotation": 60.0,
    "crafting": 3600.0,
    "predator": 300.0,
    "servers": 300.0,
    "bridge": 60.0,
}
_FALLBACK_TTL = 60.0

# L'API tolère 2 requêtes/seconde.
_MIN_INTERVAL = 0.5


class ApexClient:
    def __init__(
        self,
        api_key: str = "",
        *,
        ttl: dict[str, float] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._ttl = {**DEFAULT_TTL, **(ttl or {})}
        self._now = now
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: dict[tuple, tuple[float, Any]] = {}

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def get(self, endpoint: str, params: dict | None = None) -> Any:
        """La réponse de l'endpoint, depuis le cache si elle y est encore fraîche.

        Une erreur est retournée sous forme de chaîne et n'entre jamais dans le
        cache : une panne d'une seconde condamnerait l'endpoint tout son TTL.
        """
        key = (endpoint, tuple(sorted((params or {}).items())))
        cached = self._cache.get(key)
        if cached and cached[0] > self._now():
            return cached[1]

        try:
            value = await self._fetch(endpoint, params or {})
        except httpx.HTTPStatusError as exc:
            logger.error("Apex {ep} HTTP {code}", ep=endpoint, code=exc.response.status_code)
            return f"Apex API error (HTTP {exc.response.status_code})"
        except Exception as exc:
            logger.error("Apex {ep} error: {e}", ep=endpoint, e=exc)
            return f"Apex API error: {exc}"

        ttl = self._ttl.get(endpoint, _FALLBACK_TTL)
        self._cache[key] = (self._now() + ttl, value)
        self._purger()
        return value

    def _purger(self) -> None:
        """Retire les entrées périmées.

        Le cache n'était jamais nettoyé, et sa clé contient le pseudo demandé
        dans le chat : chaque joueur cité y laissait un payload `/bridge`
        complet, pour la durée de vie du process. Croissance monotone, bornée
        par rien.
        """
        maintenant = self._now()
        perimees = [k for k, (expire, _) in self._cache.items() if expire <= maintenant]
        for k in perimees:
            self._cache.pop(k, None)

    async def _fetch(self, endpoint: str, params: dict) -> Any:
        """Le seul point qui touche le réseau — doublé dans les tests."""
        await self._rate_limit()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_BASE_URL}/{endpoint}",
                headers={"Authorization": self._api_key},
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _rate_limit(self) -> None:
        # `self._now()` et non `time.monotonic()` : le constructeur accepte une
        # horloge injectée, utilisée pour le TTL du cache, mais cette méthode
        # lisait l'horloge réelle. Les deux divergeaient dès qu'un test en
        # fournissait une factice — couture d'injection incomplète, donc
        # trompeuse pour qui s'y fie.
        async with self._lock:
            elapsed = self._now() - self._last_request
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            self._last_request = self._now()
