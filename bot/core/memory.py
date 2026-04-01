# bot/core/memory.py
from __future__ import annotations

import asyncio
import json
import os
import time
import warnings
from datetime import date
from typing import TYPE_CHECKING, Optional

# Le qdrant-client peut être en avance sur le serveur Qdrant en production :
# le warning est purement cosmétique — les API utilisées sont stables.
warnings.filterwarnings("ignore", message="Qdrant client version", category=UserWarning)

from loguru import logger

from bot.core.memory_store import MemoryMetadata, MemoryRecord, QdrantMemoryStore
from bot.core.prompts import load_prompt

if TYPE_CHECKING:
    from bot.config import Config
    from bot.core.llm import BaseLLMClient

_SUMMARIZE_SYSTEM = load_prompt(
    "memory_summarize_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Résume la conversation en 4 à 7 lignes, "
        "texte brut, sans titre."
    ),
)

_CHUNK_SIZE = 10  # messages per summarization chunk

# ── Consolidation des souvenirs long-terme ────────────────────────────────────
# Quand un utilisateur dépasse ce nombre de souvenirs, on les consolide en un
# ensemble compact de faits essentiels pour éviter la dérive mémorielle.
_CONSOLIDATION_THRESHOLD = 25
GLOBAL_USER_ID = "global:server"
_CONSOLIDATION_SYSTEM = load_prompt(
    "memory_consolidation_system",
    fallback=(
        "Tu es le gestionnaire de mémoire long-terme de Wally. Consolide les souvenirs "
        "en 15 faits essentiels maximum, un par ligne, sans préambule."
    ),
)

_EVALUATE_SYSTEM = load_prompt(
    "memory_evaluate_system",
    fallback=(
        "Tu es le module de mémoire de Wally. Évalue la complétude du souvenir. "
        'Retourne {"complete": true/false, "questions": [], "resolves": []}'
    ),
)


class MemoryService:
    def __init__(self, config: "Config"):
        self._config = config
        self._store: Optional[QdrantMemoryStore] = None
        self._store_init_attempted: bool = False
        # Sliding context window: channel_id → list[{author, content, timestamp}]
        self._context_windows: dict[str, list[dict]] = {}
        # Prelude buffer: channel_id → list[{author, content, timestamp}]
        self._prelude_windows: dict[str, list[dict]] = {}
        self._openai: Optional["BaseLLMClient"] = None
        self._db: Optional[object] = None
        # Strong refs pour les tâches fire-and-forget (consolidation, etc.)
        self._bg_tasks: set[asyncio.Task] = set()
        # Alias cache: {alias_uid: canonical_uid} pour la résolution des comptes liés
        self._alias_cache: dict[str, str] = {}
        # Verrou par utilisateur pour sérialiser les maintenances (évite les questions en double)
        self._maintenance_locks: dict[str, asyncio.Lock] = {}

    def set_openai_client(self, client: "BaseLLMClient") -> None:
        self._openai = client

    def set_db(self, db) -> None:
        self._db = db

    def _fire(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        return t

    # ── Qdrant memory store ────────────────────────────────────────────────

    def _init_store(self) -> None:
        if self._store_init_attempted:
            return
        self._store_init_attempted = True
        try:
            qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
            collection_name = os.getenv("QDRANT_COLLECTION_NAME", "wally_memory")
            self._store = QdrantMemoryStore(qdrant_url, collection_name, self._db)
            logger.info("QdrantMemoryStore initialized (url={})", qdrant_url)
        except Exception as exc:
            logger.warning("QdrantMemoryStore init failed: {e}", e=exc)
            self._store = None

    @property
    def store(self) -> QdrantMemoryStore | None:
        self._init_store()
        return self._store

    def _user_id(self, platform: str, user_id: str) -> str:
        # Guard against double-prefix: if user_id already starts with "platform:",
        # strip it to avoid "discord:discord:123456" in Qdrant.
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
                self._alias_cache[f"nickname:{nickname}"] = canonical_uid
            logger.info("Nickname aliases loaded: {n}", n=len(nickname_map))
        except Exception as e:
            logger.warning("Failed to load nickname aliases: {e}", e=e)

    def add_alias(self, alias_id: str, canonical_id: str) -> None:
        """Enregistre un alias dans le cache (après acceptation d'un lien)."""
        self._alias_cache[alias_id] = canonical_id

    def remove_alias(self, alias_id: str) -> None:
        """Supprime un alias du cache (après déliaison)."""
        self._alias_cache.pop(alias_id, None)

    async def add(self, platform: str, user_id: str, content: str,
                  username: str = "", emotion_context: str = "",
                  category: str = "") -> None:
        self._init_store()
        if self._store is None:
            return
        try:
            uid = self._user_id(platform, user_id)
            date_str = date.today().isoformat()
            date_prefix = f"[{date_str}] "
            full_content = f"[{emotion_context}] {date_prefix}{content}" if emotion_context else f"{date_prefix}{content}"

            metadata = MemoryMetadata(
                user_id=uid,
                category=category or "FAIT",
                date=date_str,
                source="fact_extractor",
                platform=platform,
            )
            await self._store.upsert(uid, full_content, metadata)
            logger.debug("Memory added [{uid}]: {c}", uid=uid, c=content[:80])

            if self._db is not None:
                await self._db.upsert_memory_user(uid, platform, username)
                try:
                    count = await self._store.count(uid)
                    await self._db.execute(
                        "UPDATE memory_users SET memory_count=? WHERE user_id=?",
                        (count, uid),
                    )
                except Exception:
                    pass
            # Vérification consolidation + évaluation en arrière-plan
            self._fire(self._post_add_maintenance(uid, content))
            # Analyse automatique des liens de comptes (seulement pour les non-alias)
            raw_uid = f"{platform}:{user_id}"
            if uid == raw_uid and self._db is not None:
                from bot.core import account_linker
                threshold = getattr(self._config.bot, "link_min_confidence", 0.75)
                self._fire(account_linker.analyze_new_user(self._db, raw_uid, threshold))
        except Exception as exc:
            logger.warning("Memory add failed: {e}", e=exc)

    async def add_global(self, content: str, source: str = "fact_extractor") -> None:
        """Store a community-level fact in the global namespace.

        Bypasses consolidation, upsert_memory_user, and account_linker
        (not relevant for global facts).
        """
        self._init_store()
        if self._store is None:
            return
        try:
            date_str = date.today().isoformat()
            full_content = f"[{date_str}] {content}"
            metadata = MemoryMetadata(
                user_id=GLOBAL_USER_ID,
                category="FAIT",
                date=date_str,
                source=source,
                platform="global",
            )
            await self._store.upsert(GLOBAL_USER_ID, full_content, metadata)
            logger.info("Global memory added: {c}", c=content[:80])
        except Exception as exc:
            logger.warning("Global memory add failed: {e}", e=exc)

    async def search_global(self, query: str) -> str:
        """Search the global namespace for community-level knowledge."""
        self._init_store()
        if self._store is None:
            return ""
        if not query or not query.strip():
            return ""
        try:
            min_score = self._config.bot.memory_search_min_score
            results = await self._store.search(
                query, user_id=GLOBAL_USER_ID, limit=5, min_score=min_score,
            )
            memories = [r.text for r in results if r.text]
            return "\n".join(memories)
        except Exception as exc:
            logger.warning("Global memory search failed: {e}", e=exc)
            return ""

    async def _post_add_maintenance(self, uid: str, content: str) -> None:
        """Run consolidation (if threshold exceeded) or evaluation — single get_all."""
        if self._store is None:
            return
        lock = self._maintenance_locks.setdefault(uid, asyncio.Lock())
        async with lock:
            try:
                all_records = await self._store.get_all(uid)
                if len(all_records) > _CONSOLIDATION_THRESHOLD:
                    await self._consolidate(uid, all_records)
                else:
                    await self._evaluate(uid, content, all_records)
            except Exception as exc:
                logger.warning("Post-add maintenance failed for {uid}: {e}", uid=uid, e=exc)

    async def _consolidate(self, uid: str, records: list[MemoryRecord] | None = None) -> None:
        """Consolide les souvenirs si leur nombre dépasse le seuil.

        Stratégie safe : on ajoute la synthèse AVANT de supprimer les anciens.
        """
        if self._openai is None or self._store is None:
            return
        try:
            if records is None:
                records = await self._store.get_all(uid)
            if len(records) <= _CONSOLIDATION_THRESHOLD:
                return

            logger.info(
                "Consolidating {n} memories for {uid}",
                n=len(records),
                uid=uid,
            )
            old_ids = [r.id for r in records]
            memories_text = "\n".join(
                f"- {r.text}" for r in records if r.text
            )
            consolidated = await self._openai.complete(
                _CONSOLIDATION_SYSTEM,
                [{"role": "user", "content": memories_text}],
                purpose="memory_consolidation",
            )
            # Ajouter la synthèse en premier — la donnée est safe dès ici
            metadata = MemoryMetadata(
                user_id=uid,
                category="FAIT",
                date=date.today().isoformat(),
                source="consolidation",
                platform=uid.split(":")[0] if ":" in uid else "",
            )
            await self._store.upsert(uid, consolidated, metadata)
            # Supprimer les anciens souvenirs en batch
            try:
                deleted = await self._store.delete_batch(old_ids)
            except Exception as del_exc:
                logger.warning(
                    "Failed to batch-delete old memories: {e}", e=del_exc,
                )
                deleted = 0
            logger.info(
                "Memory consolidated for {uid}: {n} entries -> 1 ({d}/{n} old deleted)",
                uid=uid,
                n=len(records),
                d=deleted,
            )
            # Update cached memory count in DB
            if self._db is not None:
                try:
                    new_count = await self._store.count(uid)
                    await self._db.execute(
                        "UPDATE memory_users SET memory_count=? WHERE user_id=?",
                        (new_count, uid),
                    )
                except Exception as count_exc:
                    logger.debug("Failed to update memory_count after consolidation: {e}", e=count_exc)
        except Exception as exc:
            logger.warning("Memory consolidation failed: {e}", e=exc)

    async def _evaluate(self, uid: str, content: str, records: list[MemoryRecord] | None = None) -> None:
        """Evaluate memory completeness and create follow-up questions if needed."""
        if self._openai is None or self._db is None or self._store is None:
            return
        try:
            # Get existing pending questions for context
            pending = await self._db.get_all_pending_questions(uid)
            pending_block = ""
            if pending:
                lines = [f"- [ID {q['id']}] {q['question']}" for q in pending]
                pending_block = "\nQuestions en attente :\n" + "\n".join(lines)

            # Include existing memories so the LLM doesn't ask about known info
            existing_block = ""
            try:
                if records is None:
                    records = await self._store.get_all(uid)
                if records:
                    mem_lines = [r.text for r in records[:30] if r.text]
                    if mem_lines:
                        existing_block = "\nSouvenirs existants :\n" + "\n".join(f"- {m}" for m in mem_lines)
            except Exception:
                pass  # Non-critical, continue without existing memories

            user_msg = f"Nouveau souvenir : {content}{existing_block}{pending_block}"
            raw = await self._openai.complete(
                _EVALUATE_SYSTEM,
                [{"role": "user", "content": user_msg}],
                purpose="memory_evaluate",
            )
            # Strip markdown code blocks if present (LLMs sometimes wrap JSON)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)

            # Insert new questions (max 1 to avoid redundant questions)
            existing_q_texts = {q["question"].strip().lower() for q in pending}
            questions = result.get("questions", [])[:1]
            for q in questions:
                question = q.get("question", "").strip()
                priority = q.get("priority", "medium")
                if question and priority in ("high", "medium") and question.lower() not in existing_q_texts:
                    await self._db.insert_memory_question(uid, content, question, priority)
                    logger.debug("Memory question created for {uid}: {q}", uid=uid, q=question)

            # Resolve answered questions (LLM may return int or string IDs)
            for qid in result.get("resolves", []):
                try:
                    await self._db.resolve_question(int(qid))
                    logger.debug("Memory question {id} resolved by new memory", id=qid)
                except (ValueError, TypeError):
                    pass

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("Memory evaluate parse error: {e}", e=exc)
        except Exception as exc:
            logger.warning("Memory evaluate failed: {e}", e=exc)

    async def get_pending_question_directive(self, platform: str, user_id: str) -> str:
        """Return a prompt directive for the most important pending question, or ''."""
        if self._db is None:
            return ""
        try:
            uid = self._user_id(platform, user_id)
            q = await self._db.get_pending_question(uid)
            if not q:
                return ""
            await self._db.increment_question_attempts(q["id"])
            return (
                f"\n--- Question en attente ---\n"
                f"Si l'occasion se présente naturellement dans la conversation, "
                f"essaie de savoir : {q['question']}\n"
                f"Ne force pas — si le sujet ne vient pas, laisse tomber."
            )
        except Exception as exc:
            logger.warning("get_pending_question_directive failed: {e}", e=exc)
            return ""

    async def delete_user_memories(self, platform: str, user_id: str) -> None:
        """Delete all long-term memories for a given user (e.g. orphan cleanup)."""
        self._init_store()
        if self._store is None:
            return
        try:
            uid = self._user_id(platform, user_id)
            await self._store.delete_by_user(uid)
            logger.info(
                "delete_user_memories: removed all memories for {uid}",
                uid=uid,
            )
        except Exception as exc:
            logger.warning("delete_user_memories failed: {e}", e=exc)

    async def reset_all(self) -> None:
        """Clear all context windows and all long-term memories."""
        self._context_windows.clear()
        self._prelude_windows.clear()
        logger.info("Memory context windows cleared")
        if self._store is not None:
            try:
                await self._store.reset()
                logger.info("Long-term memory reset")
            except Exception as exc:
                logger.warning("Memory reset failed: {e}", e=exc)

    async def get_all(self, platform: str, user_id: str) -> str:
        """Retourne toutes les mémoires d'un utilisateur sous forme de texte."""
        self._init_store()
        if self._store is None:
            return ""
        try:
            uid = self._user_id(platform, user_id)
            records = await self._store.get_all(uid)
            if not records:
                return ""
            return "\n".join(r.text for r in records if r.text)
        except Exception as exc:
            logger.warning("get_all failed: {e}", e=exc)
            return ""

    async def search(
        self, platform: str, user_id: str, query: str,
        context_messages: list[dict] | None = None,
    ) -> str:
        self._init_store()
        if self._store is None:
            return ""
        if not query or not query.strip():
            return ""
        try:
            uid = self._user_id(platform, user_id)
            min_score = self._config.bot.memory_search_min_score

            # Build context query from prelude (exclude Wally's messages)
            context_query = ""
            if context_messages:
                context_texts = [
                    m["content"] for m in context_messages[-5:]
                    if m.get("author", "").lower() != "wally"
                ]
                context_query = "\n".join(context_texts).strip()

            # Run searches (parallel if context available)
            if context_query and context_query != query.strip():

                async def _empty() -> list[MemoryRecord]:
                    return []

                primary_coro = self._store.search(query, user_id=uid, limit=5, min_score=min_score)
                context_coro = self._store.search(context_query, user_id=uid, limit=5, min_score=min_score)
                direct_results, context_results = await asyncio.gather(
                    primary_coro, context_coro,
                )
            else:
                direct_results = await self._store.search(
                    query, user_id=uid, limit=5, min_score=min_score,
                )
                context_results = []

            # Merge and deduplicate by memory content, keeping best score
            seen: dict[str, float] = {}
            for r in direct_results:
                if r.text:
                    seen[r.text] = max(seen.get(r.text, 0.0), r.score)
            for r in context_results:
                if r.text:
                    seen[r.text] = max(seen.get(r.text, 0.0), r.score)

            if not seen:
                return ""

            # Sort by score descending
            sorted_memories = sorted(seen.items(), key=lambda x: x[1], reverse=True)
            return "\n".join(mem for mem, _ in sorted_memories)

        except Exception as exc:
            logger.warning("Memory search failed: {e}", e=exc)
            return ""

    async def search_top_match(
        self, platform: str, user_id: str, query: str,
    ) -> tuple[str, float] | None:
        """Return the single best memory match with its score, or None.

        Unlike search(), this does a single Qdrant query (no dual-query)
        and returns the raw score for threshold comparison.
        """
        self._init_store()
        if self._store is None:
            return None
        if not query or not query.strip():
            return None
        try:
            uid = self._user_id(platform, user_id)
            min_score = self._config.bot.memory_search_min_score
            results = await self._store.search(
                query, user_id=uid, limit=3, min_score=min_score,
            )
            if results:
                return (results[0].text, results[0].score)
            return None
        except Exception as exc:
            logger.warning("search_top_match failed: {e}", e=exc)
            return None

    async def search_relationships(
        self, platform: str, participants: list[str],
        context: str = "",
    ) -> str:
        """Search for REL facts involving the given participants.

        Uses semantic search with category filter instead of scanning all memories.
        """
        self._init_store()
        if self._store is None or not participants:
            return ""
        try:
            min_score = self._config.bot.memory_search_min_score
            query = context or " ".join(participants)
            seen: set[str] = set()
            for user_id in participants[:5]:  # limit for perf
                uid = self._user_id(platform, user_id)
                results = await self._store.search(
                    query, user_id=uid, filters={"category": "REL"},
                    limit=10, min_score=min_score,
                )
                for r in results:
                    if r.text and r.text not in seen:
                        seen.add(r.text)
            return "\n".join(seen) if seen else ""
        except Exception as exc:
            logger.warning("search_relationships failed: {e}", e=exc)
            return ""

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
        return [summary_entry]

    async def _summarize_messages(self, messages: list[dict]) -> str:
        """Multi-pass sliding summarization."""
        summaries: list[str] = []
        for i in range(0, len(messages), _CHUNK_SIZE):
            chunk = messages[i : i + _CHUNK_SIZE]
            chunk_text = "\n".join(
                f"[{m['author']}]: {m['content']}" for m in chunk
            )
            summary = await self._openai.complete(
                _SUMMARIZE_SYSTEM,
                [{"role": "user", "content": chunk_text}],
                purpose="context_summary",
            )
            summaries.append(summary)

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n---\n".join(summaries)
        return await self._openai.complete(
            _SUMMARIZE_SYSTEM,
            [{"role": "user", "content": combined}],
            purpose="context_summary_final",
        )
