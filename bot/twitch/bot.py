# bot/twitch/bot.py
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Optional

from twitchio.ext import commands
from loguru import logger

# Cadence de surveillance d'EventSub. Assez court pour qu'une panne se compte en
# secondes de silence et non en dizaines de minutes, assez long pour rester
# anodin côté quota Helix (une requête GET, non facturée en création).
EVENTSUB_HEALTHCHECK_SECONDS = 60
# Plafond du recul entre deux relances EventSub infructueuses. 60 s × 2^n, borné
# à une demi-heure : assez pour laisser le budget de CRÉATION se recharger, assez
# court pour qu'une panne passagère se répare toute seule dans le live.
EVENTSUB_RESTART_BACKOFF_MAX_S = 1800

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.apex.duel_runner import DuelRunner
    from bot.db.database import Database
    from bot.core.emotion import EmotionEngine
    from bot.intelligence.memory.service import MemoryService
    from bot.core.llm import BaseLLMClient
    from bot.intelligence.prompts import PromptBuilder
    from bot.core.language import LanguageDetector
    from bot.twitch.token_manager import TwitchTokenManager
    from bot.twitch.api import TwitchAPI
    from bot.intelligence.persona import PersonaService


async def reprendre_visites(db, chaines_invitees) -> dict[str, dict]:
    """Les visites laissées ouvertes par le process précédent, par chaîne.

    Le lien chaîne → `visit_id` vivait en RAM. Après un rebuild, la ligne
    `twitch_visits` restait ouverte pour toujours : jamais finalisée, donc
    jamais résumée par le LLM, donc absente du journal du jour. Rien de neuf
    n'est rangé ici — la table portait déjà tout —, il manquait la RELECTURE.

    Seules les chaînes ENCORE dans la config sont reprises : une visite d'une
    chaîne qu'on a quittée entre-temps ne nous regarde plus, et la reprendre
    ferait croire à une visite en cours qui n'existe pas.

    Ne lève jamais : un démarrage ne se joue pas sur un historique.
    """
    if db is None:
        return {}
    voulues = {str(c).lower() for c in (chaines_invitees or [])}
    if not voulues:
        return {}
    try:
        ouvertes = await db.visites_ouvertes()
    except Exception as exc:  # noqa: BLE001 — un historique illisible n'empêche pas de démarrer
        logger.warning("Visites ouvertes illisibles : {e!r}", e=exc)
        return {}
    reprises: dict[str, dict] = {}
    for ligne in ouvertes or []:
        nom = str((ligne or {}).get("channel") or "").lower()
        if nom not in voulues:
            continue
        reprises[nom] = {
            "visit_id": ligne.get("id"),
            "msg_count": int(ligne.get("msg_count") or 0),
            "joined_at": float(ligne.get("joined_at") or 0.0),
        }
    if reprises:
        logger.info("Visites reprises du process précédent : {c}",
                    c=", ".join(sorted(reprises)))
    return reprises


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
        self._init_eventsub_restart_state()
        self.fact_extractor = None  # set by main.py after construction
        # Duel Apex payé en points de chaîne — construit par main.py quand la
        # config l'active. Absent, la sonde s'arrête d'elle-même et l'achat
        # d'une récompense est remboursé (cf. `events/redemptions.py`).
        self.duel_runner: Optional["DuelRunner"] = None
        # Dashboard integration — set to AppState by main.py after construction
        self.dashboard_state = None  # type: ignore[assignment]
        # Cached stream info — alimenté par StreamWatcher (bot.core.stream_watcher)
        # via son callback on_poll, câblé dans main.py. Source unique : le watcher
        # est le seul poller du statut home (Azrael), partagé avec la cognition.
        self._stream_info: dict = {
            "live": False, "title": None, "category": None, "viewers": 0, "started_at": None,
        }
        # StreamWatcher injecté par main.py (None si Twitch actif sans watcher).
        self.stream_watcher = None
        # StreamFeed injecté par main.py : flux PASSIF du live (jeu, audience,
        # raids/subs, chat) restitué au prompt comme contexte d'ambiance. None →
        # rien n'est enregistré, les appelants sont tous best-effort.
        self.stream_feed = None

    def is_on_cooldown(self, user_id: str) -> bool:
        last = self._cooldowns.get(user_id, 0.0)
        return (time.time() - last) < self.config.twitch.cooldown_seconds

    def set_cooldown(self, user_id: str) -> None:
        now = time.time()
        # Purge paresseuse : une entrée par utilisateur Twitch croyait
        # indéfiniment sur un process qui tourne des semaines, alors qu'un
        # cooldown écoulé ne sert plus à rien (cf. `_open_questions` côté
        # Discord, qui purge en citant le même motif).
        if len(self._cooldowns) > 512:
            window = self.config.twitch.cooldown_seconds
            self._cooldowns = {
                uid: at for uid, at in self._cooldowns.items() if now - at < window
            }
        self._cooldowns[user_id] = now

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
        # Par le même chemin sérialisé que les redémarrages : le dashboard peut
        # retirer une chaîne invitée pendant que le boot souscrit encore, et deux
        # créations concurrentes laissent deux clients vivants (double réception).
        await self._restart_eventsub()
        await asyncio.gather(
            self._irc_run(),
            self._token_refresh_loop(),
            self._poll_guest_streams(),
            self._resolve_missing_usernames(),
            self._eventsub_watchdog(),
            self._duel_poll_loop(),
            self._emote_refresh_loop(),
        )

    async def _emote_refresh_loop(self) -> None:
        """Tient à jour les emotes que Wally a le droit d'écrire dans le chat.

        Le catalogue Twitch bouge lentement (une emote ajoutée par la chaîne, un
        abonnement offert au bot) : six heures suffisent, et l'appel est gratuit
        en quota. L'amorçage des compteurs ne se fait qu'une fois — il relit des
        journaux, pas l'API.
        """
        from bot.core.twitch_emotes import active_emote_registry, refresh_from_api

        amorce = False
        while True:
            await refresh_from_api(self.twitch_api)
            if not amorce:
                amorce = True
                racine = getattr(getattr(self, "conv_log", None), "root", None)
                if racine is not None:
                    # En thread : c'est de la lecture disque, elle n'a rien à
                    # faire dans la boucle d'événements (même règle que le reste
                    # du projet pour les I/O bloquantes).
                    await asyncio.to_thread(
                        active_emote_registry().seed_from_logs, racine
                    )
            await asyncio.sleep(6 * 3600)

    async def _duel_poll_loop(self) -> None:
        """Sonde le duel Apex en cours, s'il y en a un.

        Le corps vit dans `bot.core.apex.duel_runner` : il s'y teste sans monter
        un bot twitchio, et c'est là que se vérifient ses deux exigences —
        aucune requête hors duel, et une horloge murale.

        L'attribut est passé en LECTURE différée : `main.py` le pose pendant le
        démarrage, et rien ne garantit qu'il l'ait fait avant ce `gather`.
        """
        from bot.core.apex.duel_runner import boucle_sonde

        await boucle_sonde(lambda: self.duel_runner)

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
                    # SURVEILLÉ, et pas seulement attendu. twitchio ne pose
                    # `_closing` que sur une `AuthenticationError` au connect ou
                    # sur `close()` : le chemin « Login unsuccessful » appelle
                    # `_close()` SANS le poser. On attendait alors pour toujours
                    # une WebSocket morte — l'envoi vers les chaînes invitées
                    # mourait en silence total et ne repartait jamais. C'est le
                    # pendant IRC de la surdité EventSub du 2026-08-08, sans son
                    # watchdog.
                    while not self._closing.is_set():
                        try:
                            await asyncio.wait_for(self._closing.wait(), timeout=30)
                        except asyncio.TimeoutError:
                            pass
                        if self._closing.is_set():
                            break
                        if not self._irc_vivante():
                            logger.warning("Twitch IRC: connexion morte — reconnexion")
                            break
                    else:
                        return  # arrêt propre
                    if self._closing.is_set():
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Twitch IRC connection failed, retrying in 10s: {e}", e=exc)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    def _irc_vivante(self) -> bool:
        """La connexion IRC est-elle encore utilisable ?

        `is_alive` n'existe pas sur toutes les versions de twitchio : en cas de
        doute on répond OUI, pour ne jamais reconnecter en boucle sur une sonde
        qu'on ne sait pas lire.
        """
        conn = getattr(self, "_connection", None)
        if conn is None:
            return False
        vivante = getattr(conn, "is_alive", None)
        if vivante is None:
            return True
        try:
            return bool(vivante() if callable(vivante) else vivante)
        except Exception:  # noqa: BLE001 — sonde illisible : on ne casse rien
            return True

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
        # Les visites laissées ouvertes par le process précédent. Reprises ici et
        # pas au `__init__` : c'est le premier moment où la config des chaînes
        # invitées est celle qui vaut, et où la base est ouverte.
        #
        # Elles ne sont PAS écrasées si une visite a déjà été ouverte entre-temps
        # (`add_guest_channel` pendant le démarrage) : la plus récente fait foi,
        # sinon on refermerait la neuve avec l'identifiant de l'ancienne.
        for nom, info in (await reprendre_visites(
                self.db, self.config.twitch.guest_channels)).items():
            self._active_visits.setdefault(nom, info)

    async def _token_refresh_loop(self) -> None:
        # Refresh tokens every 3h (Twitch user tokens expire after 4h).
        try:
            while True:
                await asyncio.sleep(3 * 3600)
                await self._refresh_tokens_and_maybe_restart_eventsub()
        except asyncio.CancelledError:
            pass

    async def _refresh_tokens_and_maybe_restart_eventsub(self) -> None:
        """Validate/refresh Twitch tokens, restarting EventSub only if a token changed.

        twitchio v2 bakes token strings into its _Subscription objects and can't
        update them in-flight, so a rotated token does require rebuilding the
        EventSub client. But startup_validate() only rotates a token when it has
        actually expired (401) — the common case leaves both tokens untouched.

        Restarting EventSub unconditionally on every cycle tore down and recreated
        every subscription needlessly, hammering Twitch's per-endpoint subscription
        rate limit (429 Ratelimit Reached) and surfacing twitchio's internal
        reconnect bugs (InvalidStateError, bad-frame noise). We now restart only
        when a token really changed, and swallow any restart error as a concise
        WARNING so it never leaks as an unhandled task traceback.
        """
        bot_before = self.token_manager.bot_token
        streamer_before = self.token_manager.streamer_token
        try:
            await self.token_manager.startup_validate()
        except Exception as exc:
            logger.warning("Twitch token validation cycle failed: {e}", e=exc)
            return

        token_changed = (
            self.token_manager.bot_token != bot_before
            or self.token_manager.streamer_token != streamer_before
        )
        if not token_changed:
            logger.debug("Twitch token refresh: tokens unchanged, EventSub left intact")
            return

        # L'IRC AUSSI. twitchio fige le token dans `WSConnection._token` et
        # `TwitchHTTP.token` au constructeur, et `authenticate()` renvoie
        # `PASS oauth:{_token}` à CHAQUE reconnexion. Sans cette propagation, la
        # première reconnexion suivant une rotation (toutes les 3 h) échouait :
        # twitchio journalise « Login unsuccessful » via `logging`, invisible
        # dans loguru, puis ferme la session — Wally ne pouvait plus rien
        # envoyer dans les chaînes invitées jusqu'au redémarrage, sans un log.
        nouveau = self.token_manager.bot_token
        if nouveau and nouveau != bot_before:
            # `getattr` : ce sont des attributs INTERNES de twitchio, absents
            # tant que le client n'est pas construit et susceptibles de bouger
            # d'une version à l'autre. Ne jamais faire échouer le cycle de
            # rotation pour ça.
            propage = False
            for nom_objet, attribut in (("_http", "token"), ("_connection", "_token")):
                cible = getattr(self, nom_objet, None)
                if cible is None:
                    continue
                try:
                    setattr(cible, attribut, nouveau)
                    propage = True
                except Exception as exc:  # noqa: BLE001 — API interne de twitchio
                    logger.warning("Twitch: token IRC non propagé ({a}): {e}", a=attribut, e=exc)
            if propage:
                logger.info("Twitch: token IRC mis à jour après rotation")

        logger.info("Twitch token rotated — restarting EventSub to pick up new token")
        try:
            await self._restart_eventsub()
        except Exception as exc:
            logger.warning("EventSub restart after token refresh failed: {e}", e=exc)

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
        from bot.intelligence.prompts import load_prompt
        left_at = time.time()

        summary: str | None = None
        try:
            # Récupérer les messages capturés pendant la visite
            context = self.memory.get_context(f"twitch:{channel}")
            system_prompt = load_prompt(
                "twitch_visit_summary",
                fallback=(
                    f"Tu es {self.config.bot.name}. Résume en 3-5 lignes à la première personne "
                    f"ta visite sur la chaîne Twitch de {channel}, style carnet de voyage."
                ),
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

    def _eventsub_watched_tokens(self) -> list[tuple[str, str]]:
        """Les jeux de souscriptions à surveiller — un par token utilisé.

        Une souscription EventSub n'est **visible que du token qui l'a créée**.
        `start_eventsub_client` en crée avec deux tokens : follow/raid/chat avec
        celui du bot, abonnements/resubs/gifts/cheer/points de chaîne avec celui
        du streamer. Sonder le seul token du bot rendait donc le chien de garde
        structurellement aveugle à la moitié des souscriptions — et précisément
        à celles qui portent les revenus de la chaîne.

        Vécu le 2026-08-13 en plein live : les six souscriptions du streamer
        étaient toutes en `websocket_disconnected` (achat d'une récompense de
        points de chaîne jamais reçu) pendant que les six du bot répondaient
        `enabled`. Le chien de garde ne voyait que ces dernières et concluait
        que tout allait bien.

        Le token streamer peut être absent (`STREAMER_ACCESS_TOKEN` vide) : dans
        ce cas aucune souscription streamer n'a été créée, il n'y a rien à
        surveiller de ce côté.
        """
        sides: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, token in (
            ("bot", self.token_manager.bot_token),
            ("streamer", self.token_manager.streamer_token),
        ):
            if token and token not in seen:
                seen.add(token)
                sides.append((label, token))
        return sides

    async def _check_eventsub_alive(self) -> None:
        """Relance EventSub si Twitch ne reconnaît plus les souscriptions d'un côté.

        Une WebSocket EventSub peut mourir sans un mot dans les logs — une
        coupure réseau de quelques secondes suffit. Twitch révoque alors les
        souscriptions de la session, twitchio v2 (non maintenu) ne se réabonne
        pas, et Wally devient SOURD sur Twitch jusqu'au prochain redémarrage
        manuel. Vécu le 2026-08-08 : plus de vingt minutes de silence en plein
        live, sans la moindre erreur journalisée.

        twitchio ouvre **une WebSocket par token** : les deux jeux de
        souscriptions meurent séparément, et c'est bien un seul côté qui est
        tombé le 2026-08-13. La surveillance interroge donc chaque token
        (cf. `_eventsub_watched_tokens`) et se déclenche dès que **l'un** d'eux
        ne répond plus rien.

        `None` veut dire « je n'ai pas pu demander », pas « il n'y a plus rien » :
        un côté muet ne compte ni comme mort ni comme vivant, sans quoi une
        coupure réseau — la cause même de l'incident — déclencherait des
        relances en boucle.
        """
        from bot.twitch.events import count_active_subscriptions

        if self._eventsub_restart_pending or self._eventsub_restart_lock.locked():
            return  # une reconstruction est en cours : elle passe par 0 souscription

        client_id = os.getenv("TWITCH_CLIENT_ID", "").strip()
        morts: list[str] = []
        vivants: list[str] = []
        muets: list[str] = []
        for label, token in self._eventsub_watched_tokens():
            actives = await count_active_subscriptions(client_id, token)
            if actives is None:
                muets.append(label)
            elif actives > 0:
                vivants.append(label)
            else:
                morts.append(label)

        if muets:
            logger.debug(
                "EventSub: état des souscriptions indisponible côté {c}",
                c=", ".join(muets),
            )

        if not morts:
            if vivants:
                # Le service est rendu : on oublie l'historique d'échecs.
                self._eventsub_zero_readings = 0
                self._eventsub_failed_restarts = 0
            return

        # Deux lectures à zéro AVANT d'agir : une reconstruction dure une
        # quinzaine de secondes et passe elle-même par zéro souscription.
        self._eventsub_zero_readings += 1
        if self._eventsub_zero_readings < 2:
            logger.debug(
                "EventSub: 0 souscription côté {c} (1re lecture) — on confirme au tour suivant",
                c=", ".join(morts),
            )
            return

        # Backoff : la relance rejoue `purge_stale_subscriptions` + 9 créations.
        # Quand la cause est structurelle (scope manquant, `TWITCH_BROADCASTER_ID`
        # vide, quota de CRÉATION épuisé), elle échoue à l'identique et repartait
        # 60 s plus tard, indéfiniment — en martelant justement la ressource dont
        # le budget se recharge en MINUTES, donc en empêchant la recharge qui
        # l'aurait débloquée. Et chaque tour laissait une reprise différée de plus.
        maintenant = time.monotonic()
        attente = min(
            EVENTSUB_RESTART_BACKOFF_MAX_S,
            EVENTSUB_HEALTHCHECK_SECONDS * (2 ** self._eventsub_failed_restarts),
        )
        if maintenant - self._eventsub_last_restart_at < attente:
            logger.debug(
                "EventSub: relance différée ({r} échec(s), encore {s:.0f}s)",
                r=self._eventsub_failed_restarts,
                s=attente - (maintenant - self._eventsub_last_restart_at),
            )
            return

        # Nommer le côté tombé : le message précédent ne le distinguait pas, et
        # c'est ce qui a rendu l'incident du 2026-08-13 invisible dans les logs.
        logger.warning(
            "EventSub: plus aucune souscription vivante côté {c} — relance "
            "(tentative {n})",
            c=" + ".join(morts), n=self._eventsub_failed_restarts + 1,
        )
        self._eventsub_last_restart_at = maintenant
        # La relance reconstruit TOUT (les deux tokens) : c'est le seul chemin
        # disponible, et le même que celui d'un ajout de chaîne invitée. Le côté
        # resté vivant est donc coupé puis recréé, soit ~15 s de silence et une
        # entame du quota de création — le recul progressif ci-dessus est ce qui
        # empêche que ça se répète en boucle.
        await self._restart_eventsub()

        # Une relance ne compte que si Twitch reconnaît à nouveau des
        # souscriptions DES DEUX CÔTÉS. Sinon on recule davantage au tour
        # suivant. Un côté muet ne prouve rien : faute de confirmation, on
        # préfère reculer que de croire la panne réglée.
        apres = {
            label: await count_active_subscriptions(client_id, token)
            for label, token in self._eventsub_watched_tokens()
        }
        restes = [label for label, n in apres.items() if not n]
        if apres and not restes:
            self._eventsub_failed_restarts = 0
            self._eventsub_zero_readings = 0
            logger.info(
                "EventSub: relance réussie ({d})",
                d=", ".join(f"{label}={n}" for label, n in apres.items()),
            )
        else:
            self._eventsub_failed_restarts += 1
            logger.warning(
                "EventSub: relance sans effet côté {c} ({n} échec(s) consécutif(s))",
                c=" + ".join(restes) or "inconnu",
                n=self._eventsub_failed_restarts,
            )

    async def _eventsub_watchdog(self) -> None:
        try:
            while True:
                await asyncio.sleep(EVENTSUB_HEALTHCHECK_SECONDS)
                try:
                    await self._check_eventsub_alive()
                except Exception as exc:  # noqa: BLE001 — la surveillance ne tombe jamais
                    logger.warning("EventSub: surveillance en échec: {e}", e=exc)
        except asyncio.CancelledError:
            pass

    def _init_eventsub_restart_state(self) -> None:
        """Sérialisation des redémarrages EventSub (cf. `_restart_eventsub`)."""
        self._eventsub_restart_lock = asyncio.Lock()
        self._eventsub_restart_pending = False
        # Backoff du watchdog (cf. `_check_eventsub_alive`).
        self._eventsub_zero_readings = 0        # sondages consécutifs à 0
        self._eventsub_failed_restarts = 0      # relances sans effet d'affilée
        self._eventsub_last_restart_at = 0.0    # time.monotonic()

    async def _restart_eventsub(self) -> None:
        """Tear down existing EventSub sockets and reconnect with fresh tokens.

        Sérialisé : la reconstruction dure une quinzaine de secondes
        (souscriptions séquentielles espacées de 1.5 s) et remet
        `_eventsub_client` à None le temps de s'exécuter. Deux appels rapprochés
        — retirer une chaîne invitée pendant qu'un token tourne, par exemple —
        se croisaient donc dans cette fenêtre : le second lisait None, ne fermait
        rien, et repartait pour une seconde série. Le client de la première
        restait vivant, orphelin mais WebSocket ouverte, et Twitch livrait chaque
        message du chat DEUX fois — Wally répondait deux fois (vécu le
        2026-08-08 sur la chaîne d'Azraël, deux souscriptions
        `channel.chat.message` actives confirmées côté Twitch).

        Au plus un redémarrage en attente : les demandes suivantes sont
        absorbées par celui qui attend, qui repartira de l'état final. Empiler
        une reconstruction par demande épuiserait le quota de CRÉATION de
        souscriptions, qui se recharge en minutes (429).
        """
        if self._eventsub_restart_pending:
            return
        self._eventsub_restart_pending = True
        try:
            async with self._eventsub_restart_lock:
                self._eventsub_restart_pending = False
                await self._do_restart_eventsub()
        except asyncio.CancelledError:
            # Le drapeau est posé AVANT l'attente du verrou. Une annulation
            # pendant cette attente (requête dashboard abandonnée via
            # `add_guest_channel`, `_poll_guest_streams`) le laissait à True pour
            # la vie du process : tout redémarrage ultérieur sortait aussitôt —
            # y compris celui déclenché par `_check_eventsub_alive`. Le watchdog
            # écrit après la surdité du 2026-08-08 se désarmait donc en silence.
            self._eventsub_restart_pending = False
            raise

    async def _do_restart_eventsub(self) -> None:
        from bot.twitch.events import cancel_retry_task, start_eventsub_client

        # AVANT de fermer quoi que ce soit : la reprise différée capture le
        # client et le token de l'appel qui l'a créée, et se réveille jusqu'à
        # 20 min plus tard. Laissée vivante, elle travaillait sur un client mort
        # — soit bloquée à vie sur un `await sub.created` jamais résolu, soit en
        # ouvrant une WebSocket hors de `_eventsub_client`, donc infermable et
        # source de double réception du chat.
        cancel_retry_task(self)

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
            # Vidé : un appelant retardataire ne doit pas pouvoir réutiliser un
            # socket mort en croyant y trouver une place libre.
            try:
                client._sockets.clear()
            except Exception as e:  # noqa: BLE001
                logger.debug("EventSub: _sockets non vidable: {e}", e=e)
            self._eventsub_client = None

        await start_eventsub_client(self)

    async def event_error(self, error: Exception, data=None) -> None:
        logger.error("Twitch error: {e}", e=error)
