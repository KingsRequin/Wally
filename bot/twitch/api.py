# bot/twitch/api.py
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import asyncio
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import unicodedata

import httpx
from loguru import logger

from bot.core.account_linker import matches_name

if TYPE_CHECKING:
    from bot.twitch.token_manager import TwitchTokenManager

# Client-ID public du site web Twitch. Il n'appartient pas à l'application :
# c'est celui que le lecteur du site présente, et le seul que l'API GraphQL
# accepte. Identique dans yt-dlp et streamlink. Rien de secret ici.
_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def _ratelimit_wait(resp, *, default: float = 1.0, cap: float = 5.0) -> float:
    """Secondes à attendre après un 429, d'après `Ratelimit-Reset` (epoch)."""
    try:
        reset = float(resp.headers.get("Ratelimit-Reset", ""))
    except (TypeError, ValueError):
        return default
    return max(default, min(cap, reset - time.time()))


# Forme canonique du « pas de live ». `get_stream()` doit TOUJOURS rendre un
# dict : tout le reste du code (StreamWatcher, build_system_prompt, handlers)
# l'indexe sans garde, et un `None` y remonte en AttributeError/TypeError.
_OFFLINE_STREAM = {
    "live": False,
    "title": None,
    "category": None,
    "viewers": 0,
    "started_at": None,
}



def _fold(text: str) -> str:
    """Minuscules sans accents : « fusée » et « fusee » se cherchent pareil."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


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

    async def send_message(
        self,
        text: str,
        broadcaster_id: Optional[str] = None,
        reply_parent_message_id: Optional[str] = None,
    ) -> None:
        """POST /helix/chat/messages. Retry once on 401 after bot token refresh.

        broadcaster_id: chaîne cible. Si None, utilise self._broadcaster_id (chaîne home).
        reply_parent_message_id: ID du message parent pour créer un thread de réponse.
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
                        json={k: v for k, v in {
                            "broadcaster_id": target,
                            "sender_id": self._bot_id,
                            "message": text,
                            "reply_parent_message_id": reply_parent_message_id,
                        }.items() if v is not None},
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
                    if resp.status_code == 429 and attempt == 0:
                        # Franchi pendant un raid : sans attente, le message
                        # était simplement perdu. Twitch donne l'instant de
                        # recharge, on le respecte plutôt que de deviner.
                        wait = _ratelimit_wait(resp)
                        logger.warning("Twitch chat API 429 — nouvel essai dans {w}s", w=wait)
                        await asyncio.sleep(wait)
                        continue
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

    async def get_users_by_ids(self, ids: list[str]) -> dict[str, str]:
        """GET /helix/users?id=... Returns {numeric_id: login_name}.

        Processes up to 100 IDs per request (Helix API limit).
        Returns empty dict on error.
        """
        if not ids:
            return {}
        result: dict[str, str] = {}
        try:
            async with httpx.AsyncClient() as client:
                # Helix allows max 100 ids per request
                for chunk_start in range(0, len(ids), 100):
                    chunk = ids[chunk_start:chunk_start + 100]
                    for attempt in range(2):
                        resp = await client.get(
                            self.USERS_URL,
                            params=[("id", uid) for uid in chunk],
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
                                    return result
                                continue
                            return result
                        resp.raise_for_status()
                        for user in resp.json().get("data", []):
                            result[user["id"]] = user["login"]
                        break
        except Exception as exc:
            logger.warning("get_users_by_ids failed: {e}", e=exc)
        return result

    # Qualité visée pour l'overlay : la vidéo y fait 540 px de large, le 1080p
    # ne serait que du poids en plus (17 Mo pour 25 s) et un démarrage plus lent.
    _CLIP_QUALITY = "720"

    async def get_clip_video_url(self, slug: str) -> Optional[dict]:
        """URL du FICHIER vidéo d'un clip, et sa durée. None si indisponible.

        ⚠️ Passe par l'API GraphQL **non officielle** de Twitch (celle qu'emploient
        yt-dlp et streamlink). L'API Helix publique n'expose aucune URL de
        lecture, et le player officiel en iframe REFUSE de démarrer tout seul
        dans un overlay — « Autoplay disabled … style visibility », faux positif
        connu et non corrigé (twitchdev/issues#1127). Une balise `<video muted>`
        alimentée par cette URL, elle, démarre toujours.

        Twitch peut changer cette API sans préavis : l'appelant DOIT savoir
        retomber sur l'iframe puis sur la carte.
        """
        slug = str(slug or "").strip()
        if not slug:
            return None
        query = (
            "query($slug: ID!){clip(slug:$slug){durationSeconds "
            "playbackAccessToken(params:{platform:\"web\",playerBackend:\"mediaplayer\","
            "playerType:\"site\"}){signature value} videoQualities{quality sourceURL}}}"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://gql.twitch.tv/gql",
                    headers={"Client-ID": _GQL_CLIENT_ID,
                             "Content-Type": "application/json"},
                    json={"query": query, "variables": {"slug": slug}},
                    timeout=10,
                )
            if resp.status_code != 200:
                logger.warning("Twitch GQL clip {c}", c=resp.status_code)
                return None
            clip = ((resp.json().get("data") or {}).get("clip")) or {}
            qualities = clip.get("videoQualities") or []
            token = clip.get("playbackAccessToken") or {}
            if not qualities or not token.get("signature"):
                return None
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Twitch GQL clip a échoué : {e}", e=exc)
            return None

        # La qualité voulue si elle existe, sinon la plus haute en dessous —
        # les qualités arrivent triées du plus grand au plus petit.
        chosen = next(
            (q for q in qualities if str(q.get("quality")) == self._CLIP_QUALITY),
            None,
        ) or next(
            (q for q in qualities
             if str(q.get("quality")).isdigit()
             and int(q["quality"]) <= int(self._CLIP_QUALITY)),
            qualities[-1],
        )
        source = str(chosen.get("sourceURL") or "")
        if not source.startswith("https://"):
            return None
        sig = quote(str(token["signature"]))
        val = quote(str(token.get("value") or ""))
        return {"url": f"{source}?sig={sig}&token={val}",
                "duration": clip.get("durationSeconds") or 0}

    async def get_last_clip(self, hours: int = 24,
                            creator: str | None = None) -> dict | None:
        """Le clip le plus RÉCENT de la chaîne, ou None.

        ⚠️ Helix trie les clips par nombre de vues, pas par date : sur une
        fenêtre longue, le dernier créé peut tomber hors du lot renvoyé. D'où
        `first=100` sur 24 h — au-delà, il faudrait paginer pour un gain nul.

        `creator` restreint au clippeur demandé — un surnom suffit (« azra »
        pour « Azrael »). Helix ne sait pas filtrer là-dessus : le tri se fait
        ici, sur le `creator_name` que renvoie l'API. À noter que la fenêtre
        reste celle de CETTE chaîne : « le dernier clip d'Azra » veut dire ce
        qu'Azra a clippé ici, pas ce qui a été clippé sur sa chaîne à lui.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        if creator:
            clips = [c for c in clips
                     if matches_name(str(c.get("creator_name") or ""), creator)]
        if not clips:
            return None
        return max(clips, key=lambda c: str(c.get("created_at") or ""))

    async def get_top_clips(self, days: int = 7, first: int = 5) -> list[dict]:
        """Les clips les plus VUS de la chaîne sur les `days` derniers jours.

        Helix trie déjà par nombre de vues, mais ce n'est écrit nulle part dans
        son contrat : on retrie ici. Un jour où l'ordre changerait, le podium
        resterait juste.
        """
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        clips.sort(key=lambda c: int(c.get("view_count") or 0), reverse=True)
        return clips[:max(1, first)]

    async def find_clip(self, query: str, days: int = 30) -> dict | None:
        """Le clip dont le TITRE colle le mieux à `query`, ou None.

        Helix ne sait pas chercher dans les titres : le tri se fait ici, sur les
        mots du titre. À pertinence égale on prend le plus vu — c'est celui que
        les gens ont en tête. Rien de convaincant : None plutôt qu'un clip au
        hasard, qu'il faudrait ensuite justifier à l'écran.
        """
        query = (query or "").strip()
        if not query:
            return None
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        clips = await self.get_recent_clips(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), first=100
        )
        mots = [m for m in _fold(query).split() if len(m) > 2]
        if not mots:
            mots = [_fold(query)]
        meilleurs: list[tuple[int, int, dict]] = []
        for clip in clips:
            titre = _fold(str(clip.get("title") or ""))
            score = sum(1 for m in mots if m in titre)
            if score:
                meilleurs.append((score, int(clip.get("view_count") or 0), clip))
        if not meilleurs:
            return None
        meilleurs.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return meilleurs[0][2]

    async def get_recent_clips(self, since_iso: str, first: int = 20) -> list[dict]:
        """GET /helix/clips — clips créés depuis `since_iso` sur la chaîne.

        Twitch n'émet AUCUN événement EventSub à la création d'un clip : la
        seule façon de les voir est d'interroger l'API. Retourne une liste vide
        en cas d'erreur — un clip manqué ne vaut pas un plantage.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Retry sur 401 comme les cinq autres méthodes Helix : sans lui,
                # un token expiré condamnait la veille des clips pour tout le
                # reste du live, et le seul indice était un `logger.debug`
                # invisible en production.
                for attempt in range(2):
                    resp = await client.get(
                        "https://api.twitch.tv/helix/clips",
                        params={
                            "broadcaster_id": self._broadcaster_id,
                            "started_at": since_iso,
                            "first": max(1, min(100, int(first))),
                        },
                        headers={
                            "Authorization": f"Bearer {self._tm.bot_token}",
                            "Client-Id": self._client_id,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 401 and attempt == 0:
                        logger.warning("Twitch clips API 401 — renouvellement du token")
                        if not await self._tm.refresh("bot"):
                            return []
                        continue
                    if resp.status_code != 200:
                        logger.warning("Twitch clips API {c}", c=resp.status_code)
                        return []
                    return resp.json().get("data") or []
                return []
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            logger.debug("Twitch clips API a échoué : {e}", e=exc)
            return []

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
                        # `break` sortait du `for`, du `async with`, PUIS de la
                        # fonction : retour implicite `None` là où tout le reste
                        # du code attend un dict. `StreamWatcher` mourait sur un
                        # AttributeError hors de son try, et `build_system_prompt`
                        # levait un TypeError — plus aucun prompt nulle part.
                        if attempt == 0:
                            logger.warning(
                                "Twitch streams API 401 — refreshing bot token and retrying"
                            )
                            refreshed = await self._tm.refresh("bot")
                            if not refreshed:
                                logger.error(
                                    "Bot token refresh failed, cannot fetch stream status"
                                )
                                return _OFFLINE_STREAM.copy()
                            continue
                        logger.error("Twitch streams API 401 after refresh, giving up")
                        return _OFFLINE_STREAM.copy()
                    resp.raise_for_status()
                    data = resp.json().get("data", [])
                    if not data:
                        return _OFFLINE_STREAM.copy()
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
            return _OFFLINE_STREAM.copy()
