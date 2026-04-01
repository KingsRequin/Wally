# bot/twitch/bot.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.core.memory import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.core.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.core.persona import PersonaService


class WallyTwitch(commands.Bot):
    def __init__(
        self,
        config: "Config",
        db: "Database",
        emotion: "EmotionEngine",
        memory: "MemoryService",
        llm: "BaseLLMClient",
        llm_secondary: "BaseLLMClient",
        prompts: "PromptBuilder",
        language: "LanguageDetector",
        token_manager: "TwitchTokenManager",
        twitch_api: "TwitchAPI",
        persona: "PersonaService",
    ):
        super().__init__(
            token=token_manager.bot_token,
            prefix="!",
            initial_channels=[],  # Channels joined dynamically via join_channels()
        )
        self.config = config
        self.db = db
        self.emotion = emotion
        self.memory = memory
        self.llm = llm
        self.llm_secondary = llm_secondary
        self.prompts = prompts
        self.language = language
        self.token_manager = token_manager
        self.twitch_api = twitch_api
        self.persona = persona
        # Per-user cooldown: {user_id: last_response_timestamp}
        self._cooldowns: dict[str, float] = {}
        # Chaînes invitées : name (lowercase) → broadcaster_id
        self._channel_ids: dict[str, str] = {}
        # Chaînes invitées ayant été détectées live au moins une fois
        self._channel_was_live: dict[str, bool] = {}
        # Visites actives sur chaînes invitées : channel_name → {visit_id, msg_count, joined_at}
        self._active_visits: dict[str, dict] = {}
        # Strong refs pour fire-and-forget tasks
        self._bg_tasks: set[asyncio.Task] = set()
        self.graph = None  # set by main.py after construction
        self.fact_extractor = None  # set by main.py after construction
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
        # Cached stream info (updated every 60s by _poll_stream_info)
        self._stream_info: dict = {
            "live": False, "title": None, "category": None, "viewers": 0, "started_at": None,
        }

    def is_on_cooldown(self, user_id: str) -> bool:
        last = self._cooldowns.get(user_id, 0.0)
        return (time.time() - last) < self.config.twitch.cooldown_seconds

    def set_cooldown(self, user_id: str) -> None:
        self._cooldowns[user_id] = time.time()

    def _fire(self, coro) -> asyncio.Task:
        """Fire-and-forget avec strong reference pour éviter la GC."""
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    async def start(self) -> None:
        """Start EventSub (reading) + IRC (sending to guest channels).

        - EventSub WebSocket : lecture de tous les messages (home + guests).
          Scopes requis : user:read:chat, user:write:chat, user:bot.
        - IRC : envoi de messages dans les chaînes invitées sans que le broadcaster
          ait besoin d'autoriser le bot. Scope requis : chat:edit.
        """
        logger.info("Twitch bot starting (EventSub + IRC)")
        from bot.twitch.events import start_eventsub_client
        await start_eventsub_client(self)
        await asyncio.gather(
            self._irc_run(),
            self._token_refresh_loop(),
            self._poll_guest_streams(),
            self._poll_stream_info(),
            self._resolve_missing_usernames(),
        )

    async def _irc_run(self) -> None:
        """Maintain IRC connection for sending messages to guest channels.

        connect() establishes the WS and returns immediately; twitchio's internal
        keep-alive handles reconnects. event_ready() fires once auth completes,
        at which point guest channels are joined.

        We retry the initial connect() on failure, then await _closing (shutdown).
        Calling connect() in a tight loop would constantly tear down and rebuild the
        connection, preventing event_ready from ever firing.
        """
        try:
            while True:
                try:
                    await self.connect()
                    await self._closing.wait()
                    return  # clean shutdown
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Twitch IRC connection failed, retrying in 10s: {e}", e=exc)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def event_ready(self) -> None:
        """Fired by twitchio when IRC authentication is complete."""
        logger.info("Twitch IRC ready as {nick}", nick=self.nick)
        if self.config.twitch.guest_channels:
            try:
                await self.join_channels(list(self.config.twitch.guest_channels))
                logger.info(
                    "IRC: joined {n} guest channel(s)", n=len(self.config.twitch.guest_channels)
                )
            except Exception as exc:
                logger.warning("IRC: failed to join guest channels: {e}", e=exc)

    async def _token_refresh_loop(self) -> None:
        # Refresh tokens every 3h (Twitch user tokens expire after 4h).
        # twitchio v2 stores token strings in _Subscription objects — they cannot be
        # updated in-flight, so restarting the EventSub client is the only reliable
        # way to pick up refreshed tokens and avoid InvalidStateError on reconnect.
        try:
            while True:
                await asyncio.sleep(3 * 3600)
                logger.info("Periodic Twitch token refresh + EventSub restart")
                await self.token_manager.startup_validate()
                await self._restart_eventsub()
        except asyncio.CancelledError:
            pass

    async def _resolve_missing_usernames(self) -> None:
        """Migration one-shot : nettoie et résout les entrées memory_users Twitch.

        1. Supprime les IDs numériques bruts sans préfixe plateforme (doublons).
        2. Résout les entrées twitch:ID sans username via l'API Helix.
        """
        try:
            await asyncio.sleep(5)  # laisse le bot finir de démarrer

            # Supprimer les IDs numériques bruts qui ont un doublon twitch: correct
            await self.db.execute("""
                DELETE FROM memory_users
                WHERE user_id NOT LIKE '%:%'
                  AND ('twitch:' || user_id) IN (SELECT user_id FROM memory_users)
            """)

            all_users = await self.db.list_memory_users()
            missing_ids = [
                u["user_id"].split(":", 1)[1]
                for u in all_users
                if u["platform"] == "twitch"
                and not u.get("username")
                and u["user_id"].startswith("twitch:")
                and u["user_id"].split(":", 1)[1].isdigit()
            ]
            if not missing_ids:
                return
            logger.info(
                "Résolution de {n} username(s) Twitch manquant(s)...", n=len(missing_ids)
            )
            resolved = await self.twitch_api.get_users_by_ids(missing_ids)
            for numeric_id, login in resolved.items():
                await self.db.upsert_memory_user(f"twitch:{numeric_id}", "twitch", username=login)
            logger.info(
                "Usernames Twitch résolus : {n}/{t}",
                n=len(resolved),
                t=len(missing_ids),
            )
        except Exception as exc:
            logger.warning("_resolve_missing_usernames failed: {e}", e=exc)

    async def _poll_guest_streams(self) -> None:
        """Vérifie toutes les 60s le statut live des chaînes invitées.

        Quand un stream se termine (transition True → False), la chaîne est
        retirée définitivement de la config.
        """
        try:
            while True:
                await asyncio.sleep(60)
                if not self._channel_ids:
                    continue
                ids = list(self._channel_ids.values())
                try:
                    statuses = await self.twitch_api.get_streams_status(ids)
                except Exception as exc:
                    logger.warning("Guest stream poll failed: {e}", e=exc)
                    continue
                # Inverser le dict pour lookup broadcaster_id → name
                id_to_name = {v: k for k, v in self._channel_ids.items()}
                for broadcaster_id, is_live in statuses.items():
                    name = id_to_name.get(broadcaster_id)
                    if not name:
                        continue
                    if is_live:
                        self._channel_was_live[name] = True
                    elif self._channel_was_live.get(name, False):
                        logger.info(
                            "Stream terminé : Wally quitte la chaîne invitée {name}", name=name
                        )
                        await self.remove_guest_channel(name)
        except asyncio.CancelledError:
            pass

    async def _poll_stream_info(self) -> None:
        """Poll home stream status every 60s to keep _stream_info up to date."""
        try:
            while True:
                try:
                    self._stream_info = await self.twitch_api.get_stream()
                except Exception as exc:
                    logger.warning("Stream info poll failed: {e}", e=exc)
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    async def add_guest_channel(self, name: str) -> Optional[str]:
        """Ajoute une chaîne invitée, résout son ID, souscrit EventSub.

        Retourne le broadcaster_id si succès, "already_added" si déjà présente,
        None si la chaîne est introuvable ou l'API indisponible.
        """
        name = name.lower()
        if name in self.config.twitch.guest_channels:
            return "already_added"
        broadcaster_id = await self.twitch_api.get_broadcaster_id(name)
        if not broadcaster_id:
            return None
        self.config.twitch.guest_channels.append(name)
        self.config.save()
        self._channel_ids[name] = broadcaster_id
        self._channel_was_live[name] = False
        await self._restart_eventsub()
        # Rejoindre la chaîne en IRC pour pouvoir y envoyer des messages
        try:
            await self.join_channels([name])
        except Exception as exc:
            logger.warning("IRC: impossible de rejoindre {name}: {e}", name=name, e=exc)
        logger.info("Wally rejoint la chaîne invitée {name} (id={bid})", name=name, bid=broadcaster_id)
        # Démarrer le tracking de la visite
        if self.db is not None:
            visit_id = await self.db.start_twitch_visit(name)
            self._active_visits[name] = {
                "visit_id": visit_id,
                "msg_count": 0,
                "joined_at": time.time(),
            }
        return broadcaster_id

    async def remove_guest_channel(self, name: str) -> None:
        """Retire une chaîne invitée de la config et redémarre EventSub."""
        name = name.lower()
        if name in self.config.twitch.guest_channels:
            self.config.twitch.guest_channels.remove(name)
            self.config.save()
        self._channel_ids.pop(name, None)
        self._channel_was_live.pop(name, None)
        # Finaliser la visite en fire-and-forget
        info = self._active_visits.pop(name, None)
        if info:
            self._fire(self._finalize_visit(
                name,
                info["visit_id"],
                info["joined_at"],
                info["msg_count"],
            ))
        # Quitter la chaîne en IRC
        try:
            await self.part_channels([name])
        except Exception as exc:
            logger.warning("IRC: impossible de quitter {name}: {e}", name=name, e=exc)
        await self._restart_eventsub()
        logger.info("Wally a quitté la chaîne invitée {name}", name=name)

    async def _finalize_visit(
        self,
        channel: str,
        visit_id: int,
        joined_at: float,
        msg_count: int,
    ) -> None:
        """Génère un résumé LLM de la visite et persiste la ligne twitch_visits."""
        from bot.core.prompts import load_prompt
        left_at = time.time()

        summary: str | None = None
        try:
            # Récupérer les messages capturés pendant la visite
            context = self.memory.get_context(f"twitch:{channel}")
            system_prompt = load_prompt(
                "twitch_visit_summary",
                fallback=(
                    "Tu es Wally. Résume en 3-5 lignes à la première personne "
                    "ta visite sur la chaîne Twitch de {channel}, style carnet de voyage."
                ).format(channel=channel),
            )
            if context:
                messages_text = "\n".join(
                    f"[{m['author']}]: {m['content']}" for m in context[-50:]
                )
                user_content = (
                    f"Chaîne visitée : {channel}\n"
                    f"Durée : {int(left_at - joined_at) // 60} minutes\n"
                    f"Messages vus :\n{messages_text}"
                )
            else:
                user_content = (
                    f"Chaîne visitée : {channel}\n"
                    f"Durée : {int(left_at - joined_at) // 60} minutes\n"
                    f"Pas de messages capturés."
                )
            summary = await self.llm_secondary.complete(
                system_prompt,
                [{"role": "user", "content": user_content}],
                purpose="twitch_visit_summary",
            )
        except Exception as exc:
            logger.warning("_finalize_visit: LLM failed for {ch}: {e}", ch=channel, e=exc)

        if self.db is not None:
            try:
                await self.db.end_twitch_visit(visit_id, left_at, msg_count, summary)
                logger.info(
                    "Visite {ch} finalisée : {d}min, {n} msgs",
                    ch=channel, d=int(left_at - joined_at) // 60, n=msg_count,
                )
            except Exception as exc:
                logger.warning("_finalize_visit: DB write failed: {e}", e=exc)

    async def _restart_eventsub(self) -> None:
        """Tear down existing EventSub sockets and reconnect with fresh tokens."""
        from bot.twitch.events import start_eventsub_client

        client = getattr(self, "_eventsub_client", None)
        if client:
            for sock in list(client._sockets):
                try:
                    if sock._pump_task and not sock._pump_task.done():
                        sock._pump_task.cancel()
                    if sock._sock and not sock._sock.closed:
                        await sock._sock.close()
                except Exception as e:
                    logger.warning("Error closing EventSub socket during restart: {e}", e=e)
            self._eventsub_client = None

        await start_eventsub_client(self)

    async def event_error(self, error: Exception, data=None) -> None:
        logger.error("Twitch error: {e}", e=error)
