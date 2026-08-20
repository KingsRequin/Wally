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
    # 15 s et non 60 : la sonde du live relève toutes les 30 s, et un TTL de
    # 60 s lui aurait servi un relevé sur deux depuis le cache — l'historique
    # aurait eu des trous invisibles, avec des paliers en escalier là où le
    # joueur enchaînait les parties.
    "bridge": 15.0,
}
_FALLBACK_TTL = 60.0

# L'API tolère 5 requêtes/seconde. Mesuré à la clé le 2026-08-13 par montée
# progressive : 3 et 5 req/s passent intégralement, à 8 req/s la 6e requête de
# la seconde prend un 429 dont le CORPS donne la limite en toutes lettres
# (« You have 5 req/s allowed »). Aucun en-tête ne l'annonce — seul
# `x-current-rate` est renvoyé, et il ne dit que le compteur courant.
#
# Ce commentaire annonçait « 2 requêtes/seconde » et bridait le client à 0,5 s :
# 60 % du débit disponible inutilisé, pour tout le projet. Il contredisait
# `watcher.py`, qui disait juste.
_MIN_INTERVAL = 0.2


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

    async def get(self, endpoint: str, params: dict | None = None,
                  *, sans_cache: bool = False) -> Any:
        """La réponse de l'endpoint, depuis le cache si elle y est encore fraîche.

        Une erreur est retournée sous forme de chaîne et n'entre jamais dans le
        cache : une panne d'une seconde condamnerait l'endpoint tout son TTL.

        `sans_cache` court-circuite le cache dans les DEUX sens — ni lu, ni
        écrit. Le duel sonde à 2 s alors que le TTL de `bridge` est de 15 s :
        sans ce chemin, il verrait sept relevés sur huit depuis la mémoire et
        raterait les mouvements de compteurs. Et ne pas écrire non plus évite
        qu'un relevé de duel devienne la réponse servie au reste du bot.
        """
        key = (endpoint, tuple(sorted((params or {}).items())))
        if not sans_cache:
            cached = self._cache.get(key)
            if cached and cached[0] > self._now():
                return cached[1]

        try:
            value = await self._fetch(endpoint, params or {})
        except httpx.HTTPStatusError as exc:
            logger.error("Apex {ep} HTTP {code}", ep=endpoint, code=exc.response.status_code)
            return f"Apex API error (HTTP {exc.response.status_code})"
        except Exception as exc:
            # `{e!r}` et non `{e}` : une panne réseau lève des exceptions dont
            # le message est VIDE (`ConnectError('')`, `ReadTimeout('')`). La
            # ligne se terminait donc sur « Apex bridge error: » et rien —
            # 215 fois en août, dont 205 sur la seule journée du 20. On
            # journalisait fidèlement l'absence d'information. Le `repr` porte
            # le TYPE, qui est ici toute la donnée utile.
            logger.error("Apex {ep} error: {e!r}", ep=endpoint, e=exc)
            return f"Apex API error: {exc!r}"

        if not sans_cache:
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
        # Client PERSISTANT : un `AsyncClient` par appel refaisait une poignée
        # de main TLS complète à chaque fois — 100 à 200 ms ajoutés à chaque
        # sonde du watcher (toutes les 90 s pendant tout le live) et à chaque
        # panneau d'overlay. Le docstring de la classe annonçait pourtant
        # « un seul objet parle au réseau ».
        client = self._http_client()
        resp = await client.get(
            f"/{endpoint}",
            headers={"Authorization": self._api_key},
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    # Déclaré ici plutôt que déduit du premier `self._http = client` : le
    # champ vaut aussi `None` (avant la première requête, et après `aclose()`),
    # et sans cette ligne le type inféré était `AsyncClient` — la remise à None
    # de `aclose()` passait alors pour une erreur.
    _http: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        client = getattr(self, "_http", None)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=10, base_url=_BASE_URL)
            self._http = client
        return client

    async def aclose(self) -> None:
        """Ferme le client HTTP persistant (arrêt du bot)."""
        client = getattr(self, "_http", None)
        if client is not None and not client.is_closed:
            await client.aclose()
        self._http = None

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
