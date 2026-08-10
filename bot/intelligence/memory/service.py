# bot/intelligence/memory/service.py
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

from loguru import logger

from bot.intelligence.prompts import load_prompt
from bot.intelligence.identity import render_identity

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.llm import BaseLLMClient

_SUMMARIZE_SYSTEM = load_prompt(
    "memory_summarize_system",
    fallback=(
        "Tu es le module de mémoire de {{BOT_NAME}}. Résume la conversation en 4 à 7 lignes, "
        "texte brut, sans titre."
    ),
    render=False,
)

_CHUNK_SIZE = 10  # messages per summarization chunk


class MemoryService:
    def __init__(self, config: "Config"):
        self._config = config
        # V2 long-term backend (set via set_embedding_backend)
        self._facts = None
        self._retrieval = None
        self._db_path: Optional[str] = None
        # Sliding context window: channel_id → list[{author, content, timestamp}]
        self._context_windows: dict[str, list[dict]] = {}
        # Prelude buffer: channel_id → list[{author, content, timestamp}]
        self._prelude_windows: dict[str, list[dict]] = {}
        self._openai: Optional["BaseLLMClient"] = None
        self._db: Optional[object] = None
        # Strong refs pour les tâches fire-and-forget
        self._bg_tasks: set[asyncio.Task] = set()
        # Alias cache: {alias_uid: canonical_uid} pour la résolution des comptes liés
        self._alias_cache: dict[str, str] = {}
        # Un verrou d'écriture mémoire par utilisateur (cf. `add`).
        self._add_locks: dict[str, asyncio.Lock] = {}

    def set_openai_client(self, client: "BaseLLMClient") -> None:
        self._openai = client

    def set_db(self, db) -> None:
        self._db = db

    def set_embedding_backend(self, db_path: str) -> None:
        """Initialise le backend mémoire V2 (FTS5/SQLite).

        La recherche passe par FTS5 BM25 (porté de jarvis-OS).
        """
        from bot.intelligence.memory.facts import SQLiteFactStore
        from bot.intelligence.memory.retrieval import MemoryRetrieval
        self._db_path = db_path
        self._facts = SQLiteFactStore(db_path)
        self._retrieval = MemoryRetrieval(self._facts)
        logger.info("MemoryService backend V2 prêt (FTS5)")

    def _fire(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    def _user_id(self, platform: str, user_id: str) -> str:
        # Guard against double-prefix: if user_id already starts with "platform:",
        # strip it to avoid "discord:discord:123456".
        if user_id.startswith(f"{platform}:"):
            user_id = user_id[len(platform) + 1:]
            logger.warning(
                "Double-prefix detected: platform={p}, user_id had prefix stripped",
                p=platform,
            )
        # Guard against cross-platform IDs: Discord snowflakes are 17-20 digits,
        # Twitch IDs are ≤12 digits. Correct the platform if mismatched.
        if user_id.isdigit():
            digits = len(user_id)
            if platform == "twitch" and digits >= 13:
                platform = "discord"
                logger.warning(
                    "Cross-platform fix: snowflake {uid} moved twitch→discord",
                    uid=user_id,
                )
            elif platform == "discord" and digits <= 12:
                platform = "twitch"
                logger.warning(
                    "Cross-platform fix: short ID {uid} moved discord→twitch",
                    uid=user_id,
                )
        raw = f"{platform}:{user_id}"
        return self._alias_cache.get(raw, raw)

    async def load_aliases(self, db) -> None:
        """Charge la carte d'alias depuis la DB (liaisons acceptées).

        Appelé au démarrage dans main.py après Database.create().
        """
        try:
            alias_map = await db.get_alias_map()
            self._alias_cache = alias_map
            logger.info("Alias cache chargé: {n} liaisons", n=len(alias_map))
        except Exception as e:
            logger.warning("Impossible de charger les alias: {e}", e=e)
        try:
            nickname_map = await db.get_nickname_alias_map()
            for nickname, canonical_uid in nickname_map.items():
                # DEUX clés pour la même liaison, chacune lue par un chemin
                # différent, et c'est voulu :
                #   `nickname:` — lu par `handlers.py` et `journal.py` ;
                #   `unknown:`  — la SEULE forme atteignable depuis `_user_id()`,
                #                 qui compose `f"{platform}:{user_id}"`.
                # `fact_extractor` posait `unknown:` à la volée mais seule
                # `nickname:` était persistée : le routage d'un pseudo non résolu
                # vers son compte canonique marchait donc jusqu'au redémarrage,
                # puis cessait en silence. Un comportement mémoire qui change au
                # reboot, sans un log.
                self._alias_cache[f"nickname:{nickname}"] = canonical_uid
                self._alias_cache[f"unknown:{nickname}"] = canonical_uid
            logger.info("Nickname aliases loaded: {n}", n=len(nickname_map))
        except Exception as e:
            logger.warning("Failed to load nickname aliases: {e}", e=e)

    def add_alias(self, alias_id: str, canonical_id: str) -> None:
        """Enregistre un alias dans le cache (après acceptation d'un lien)."""
        self._alias_cache[alias_id] = canonical_id

    def remove_alias(self, alias_id: str) -> None:
        """Supprime un alias du cache (après déliaison)."""
        self._alias_cache.pop(alias_id, None)

    # ── Long-term memory (V2 backend) ─────────────────────────────────────────

    @property
    def retrieval(self):
        """Backend de recherche V2 (MemoryRetrieval FTS5) ou None si non initialisé."""
        return self._retrieval

    @property
    def fact_store(self):
        """Store SQLite des faits atomiques (SQLiteFactStore) ou None si non initialisé.

        Exposé pour construire un MemoryIngest (réconciliation S-P-O) au bootstrap.
        """
        return self._facts

    async def add(self, platform: str, user_id: str, content: str,
                  category: str = "FAIT", username: str | None = None,
                  source: str = "fact_extractor", origin: str | None = None,
                  expires_at: "datetime | None" = None,
                  **_kw) -> None:
        if self._retrieval is None:
            logger.warning("MemoryService.add ignoré: backend V2 non initialisé")
            return
        from datetime import datetime
        from bot.intelligence.memory.facts import AtomicFact, FactCategory, _normalize
        try:
            cat = FactCategory(category)
        except ValueError:
            cat = FactCategory.FAIT
        uid = self._user_id(platform, user_id)
        # Déduplication : si un fait actif de même contenu normalisé existe déjà
        # pour cet utilisateur et cette catégorie, on le CONFIRME (support++,
        # confiance++) au lieu de créer un doublon. Évite l'accumulation que
        # l'ancien pipeline produisait (réinsertion verbatim à chaque extraction).
        #
        # Sérialisé PAR UTILISATEUR : la lecture et l'écriture sont deux
        # connexions distinctes, sans transaction commune ni contrainte d'unicité
        # en base. Discord, Twitch et la boucle cognitive écrivant en parallèle,
        # deux extractions du même fait passaient toutes deux le test de doublon
        # et créaient deux lignes — exactement l'accumulation que ce bloc dit
        # vouloir éviter. Un verrou par `uid` suffit : les écritures d'un même
        # utilisateur sont rares, celles de deux utilisateurs restent parallèles.
        async with self._verrou_ajout(uid):
            norm = _normalize(content)
            if norm:
                jumeau = await self._facts.find_same_content(uid, cat, norm)
                if jumeau is not None:
                    await self._facts.confirm(jumeau)
                    return
            # UTC NAÏF, comme partout ailleurs (`AtomicFact` et les 15 requêtes
            # de `facts.py` utilisent `utcnow()`). Ce seul point d'écriture en
            # aware faisait cohabiter deux formats dans les mêmes colonnes —
            # 4 101 lignes sur 14 400 au 2026-08-10 — et toute soustraction
            # directe entre les deux lève `TypeError`. Les helpers défensifs qui
            # recollent `tzinfo` après coup n'existent que pour ça.
            now = datetime.utcnow()
            await self._retrieval.add_fact(AtomicFact(
                user_id=uid,
                content=content, category=cat, confidence=1.0,
                source=source, origin=origin, expires_at=expires_at,
                created_at=now, last_seen_at=now,
            ))

    def _verrou_ajout(self, uid: str) -> asyncio.Lock:
        """Verrou d'écriture propre à un utilisateur (créé à la demande)."""
        verrou = self._add_locks.get(uid)
        if verrou is None:
            verrou = asyncio.Lock()
            self._add_locks[uid] = verrou
        return verrou

    @staticmethod
    def _fact_freshness(f) -> str:
        """Indication temporelle pour un fait éphémère (qui a un `expires_at`).

        Les faits déjà périmés sont filtrés en amont (search_fts) ; on n'annote
        donc que les éphémères encore valides, pour que Wally situe dans le temps
        ("tu prévoyais ça tout à l'heure / il y a 2 jours")."""
        if getattr(f, "expires_at", None) is None:
            return ""
        from datetime import datetime, timezone
        created = f.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
        if age_days < 1:
            return " (dit plus tôt aujourd'hui)"
        if age_days < 2:
            return " (dit hier)"
        return f" (dit il y a {int(age_days)} jours)"

    @classmethod
    def _format_fact(cls, f) -> str:
        line = f"- {f.content}"
        origin = getattr(f, "origin", None)
        if origin and not origin.startswith("internal"):
            line += f" [{origin}]"
        return line + cls._fact_freshness(f)

    async def search(self, platform: str, user_id: str, query: str,
                     limit: int = 20,
                     context_messages: list[dict] | None = None,
                     username_hint: str | None = None,
                     **_kw) -> str:
        if self._retrieval is None:
            return ""
        # Enrichir la requête avec les derniers messages pour un retrieval plus contextuel.
        enriched = query
        if context_messages:
            extra = " ".join(
                m.get("content", "")[:80]
                for m in context_messages[-3:]
                if m.get("content")
            )
            if extra:
                enriched = f"{query} {extra}".strip()
        facts = await self._retrieval.search(enriched, self._user_id(platform, user_id), limit=limit)
        if not facts:
            return ""
        return "\n".join(self._format_fact(f) for f in facts)

    async def get_all(self, platform: str, user_id: str) -> str:
        if self._facts is None:
            return ""
        facts = await self._facts.get_by_user(self._user_id(platform, user_id))
        return "\n".join(self._format_fact(f) for f in facts)

    async def cleanup_expired_facts(self) -> int:
        """Archive les faits éphémères dont la péremption est passée.

        Appelée par le cron de maintenance mémoire. Le rappel (search_fts) filtre
        déjà les expirés en temps réel ; cet archivage périodique les retire
        définitivement des lectures par statut. Retourne le nombre archivé."""
        if self._facts is None:
            return 0
        n = await self._facts.archive_expired()
        if n:
            logger.info("Memory cleanup: {n} faits éphémères périmés archivés", n=n)
        # Doutes jamais tranchés : sans ça, `needs_review` est une impasse — le
        # fait devient invisible au rappel donc jamais reconfirmable, et reste en
        # suspens indéfiniment.
        stale = await self._facts.archive_stale_doubts()
        if stale:
            logger.info("Memory cleanup: {n} doutes non levés archivés", n=stale)
        # Decay : une passe par nuit, la cadence pour laquelle `DECAY_RATES` est
        # calibré (0.05/nuit pour une pensée = 18 jours de durée de vie ;
        # 0.001 pour un fait sur quelqu'un = 900 jours, autant dire jamais).
        #
        # Cet appel manquait DEPUIS L'ORIGINE : la méthode existait, la colonne
        # `decay_rate` était écrite à chaque insertion, deux tests unitaires la
        # couvraient — et personne ne l'appelait. Le seul `_apply_decay` vivant est
        # celui des ÉMOTIONS (`core/emotion.py`), homonyme et sans rapport, ce qui a
        # entretenu l'illusion pendant des mois. Résultat mesuré le 2026-08-09 :
        # 7961 faits actifs sur 9122 avaient encore leur confiance d'origine, dont
        # des désirs de 47 jours à 1.0.
        decayed = await self._facts.apply_decay()
        if decayed:
            logger.info("Memory cleanup: decay appliqué à {n} faits actifs", n=decayed)
        return n + stale

    async def delete_user_memories(self, platform: str, user_id: str) -> None:
        if self._facts is None:
            return
        await self._facts.delete_by_user(self._user_id(platform, user_id))

    async def reset_all(self) -> None:
        # Les fenêtres de contexte (RAM) sont purgées indépendamment du backend V2.
        self._context_windows.clear()
        self._prelude_windows.clear()
        if self._facts is None:
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM atomic_facts")
            await db.commit()

    # ── Sliding context window ────────────────────────────────────────────────

    def append_message(self, channel_id: str, author: str, content: str, platform: str = "discord") -> None:
        window = self._context_windows.setdefault(channel_id, [])
        window.append(
            {"author": author, "content": content, "timestamp": time.time()}
        )
        max_size = self._config.bot.context_window_size
        if len(window) > max_size:
            self._context_windows[channel_id] = window[-max_size:]
        if self._db is not None:
            self._fire(self._db.log_daily_message(channel_id, author, content, platform=platform))

    def get_context(self, channel_id: str) -> list[dict]:
        return list(self._context_windows.get(channel_id, []))

    def append_prelude(self, channel_id: str, author: str, content: str) -> None:
        window = self._prelude_windows.setdefault(channel_id, [])
        window.append(
            {"author": author, "content": content, "timestamp": time.time()}
        )
        max_size = self._config.bot.prelude_window_size
        if len(window) > max_size:
            self._prelude_windows[channel_id] = window[-max_size:]

    def get_prelude(self, channel_id: str) -> list[dict]:
        return list(self._prelude_windows.get(channel_id, []))

    def get_all_contexts(self) -> list[dict]:
        """Return all messages from all channels, sorted by timestamp."""
        all_messages: list[dict] = []
        for msgs in self._context_windows.values():
            all_messages.extend(msgs)
        all_messages.sort(key=lambda m: m["timestamp"])
        return all_messages

    async def get_context_summarized_if_needed(
        self, channel_id: str
    ) -> list[dict]:
        messages = self.get_context(channel_id)
        if not messages or self._openai is None:
            return messages

        # Guard: a single summary entry is already compact — never re-summarize it.
        if len(messages) == 1 and messages[0].get("author") == "RÉSUMÉ":
            return messages

        # Rough token estimate: 4 chars ≈ 1 token
        total_chars = sum(len(m["content"]) for m in messages)
        threshold = self._config.bot.context_token_threshold
        if total_chars / 4 < threshold:
            return messages

        logger.info(
            "Context window for {ch} exceeds token threshold, summarizing",
            ch=channel_id,
        )
        # Record the timestamp boundary before the await so we can recover any
        # messages that arrive on this channel while summarization is in progress.
        snapshot_ts = messages[-1]["timestamp"]
        summary = await self._summarize_messages(messages)
        summary_entry = {
            "author": "RÉSUMÉ",
            "content": summary,
            "timestamp": time.time(),
        }
        # Preserve messages appended to the window during the await.
        current = self._context_windows.get(channel_id, [])
        added_during = [m for m in current if m["timestamp"] > snapshot_ts]
        self._context_windows[channel_id] = [summary_entry] + added_during
        # `added_during` était calculé, rangé dans la fenêtre… et absent du
        # retour : la réponse en cours ne voyait donc AUCUN des messages arrivés
        # pendant la résumance, alors qu'ils la concernent au premier chef.
        return [summary_entry] + added_during

    async def _summarize_messages(self, messages: list[dict]) -> str:
        """Multi-pass sliding summarization."""
        summaries: list[str] = []
        for i in range(0, len(messages), _CHUNK_SIZE):
            chunk = messages[i : i + _CHUNK_SIZE]
            chunk_text = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in chunk
            )
            summary = await self._openai.complete(
                render_identity(_SUMMARIZE_SYSTEM),
                [{"role": "user", "content": chunk_text}],
                purpose="context_summary",
            )
            summaries.append(summary)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._openai.complete(
            render_identity(_SUMMARIZE_SYSTEM),
            [{"role": "user", "content": combined}],
            purpose="context_summary_final",
        )
