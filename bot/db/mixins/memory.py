from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import aiosqlite
from loguru import logger


class MemoryMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Memory users tracking ─────────────────────────────────────────────────────

    @staticmethod
    def _fix_platform(user_id: str, platform: str) -> tuple[str, str]:
        """Ensure platform matches the raw ID format in user_id.

        Discord snowflakes are 17-20 digit integers.
        Twitch numeric IDs are typically <=12 digits.
        If the raw ID doesn't match the claimed platform, swap to the correct one.
        """
        if ":" not in user_id:
            return user_id, platform

        prefix, raw = user_id.split(":", 1)
        if not raw.isdigit():
            return user_id, platform

        digits = len(raw)
        is_snowflake = digits >= 13  # Discord snowflakes: 17-20 digits, never <13
        is_twitch_id = digits <= 12  # Twitch numeric IDs: up to ~10 digits

        fixed_platform = prefix
        if prefix == "twitch" and is_snowflake:
            fixed_platform = "discord"
            user_id = f"discord:{raw}"
            logger.warning(
                "Platform fix: {old} -> {new} (snowflake detected in twitch ns)",
                old=f"twitch:{raw}", new=user_id,
            )
        elif prefix == "discord" and is_twitch_id:
            fixed_platform = "twitch"
            user_id = f"twitch:{raw}"
            logger.warning(
                "Platform fix: {old} -> {new} (short ID detected in discord ns)",
                old=f"discord:{raw}", new=user_id,
            )

        return user_id, fixed_platform

    async def upsert_memory_user(
        self, user_id: str, platform: str, username: str = "", avatar_url: str = "",
    ) -> None:
        user_id, platform = self._fix_platform(user_id, platform)
        await self.execute(
            "INSERT INTO memory_users(user_id, platform, last_updated, username, avatar_url)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   last_updated=excluded.last_updated,"
            "   platform=excluded.platform,"
            "   username=COALESCE(NULLIF(excluded.username,''), memory_users.username),"
            "   avatar_url=COALESCE(NULLIF(excluded.avatar_url,''), memory_users.avatar_url)",
            (user_id, platform, time.time(), username or None, avatar_url or None),
        )

    # ── Memory questions ───────────────────────────────────────────────────

    async def insert_memory_question(
        self, user_id: str, memory_text: str, question: str, priority: str = "medium"
    ) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO memory_questions (user_id, memory_text, question, priority, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_text, question, priority, time.time()),
        )

    async def get_pending_question(
        self, user_id: str, max_attempts: int = 3, retry_after_seconds: float = 86400.0
    ) -> dict | None:
        retry_cutoff = time.time() - retry_after_seconds
        cursor = await self._conn.execute(
            "SELECT * FROM memory_questions"
            " WHERE user_id = ? AND resolved = 0"
            "   AND (attempts < ? OR (last_attempt_at IS NOT NULL AND last_attempt_at < ?))"
            " ORDER BY"
            "   CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,"
            "   created_at ASC"
            " LIMIT 1",
            (user_id, max_attempts, retry_cutoff),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_pending_questions(self, user_id: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM memory_questions WHERE user_id = ? AND resolved = 0",
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def increment_question_attempts(self, question_id: int) -> None:
        await self.execute(
            "UPDATE memory_questions SET attempts = attempts + 1, last_attempt_at = ? WHERE id = ?",
            (time.time(), question_id),
        )

    async def resolve_question(self, question_id: int) -> None:
        await self.execute(
            "UPDATE memory_questions SET resolved = 1 WHERE id = ?",
            (question_id,),
        )

    async def update_question(self, question_id: int, question: str) -> None:
        await self.execute(
            "UPDATE memory_questions SET question = ? WHERE id = ?",
            (question, question_id),
        )

    async def delete_question(self, question_id: int) -> None:
        await self.execute(
            "DELETE FROM memory_questions WHERE id = ?",
            (question_id,),
        )

    async def cleanup_old_questions(self, max_age_days: int = 30) -> None:
        cutoff = time.time() - max_age_days * 86400
        await self.execute(
            "DELETE FROM memory_questions WHERE resolved = 1 OR created_at < ?",
            (cutoff,),
        )

    async def delete_memory_user(self, user_id: str) -> None:
        """Supprime un utilisateur de memory_users (apres fusion de comptes)."""
        await self.execute("DELETE FROM memory_users WHERE user_id = ?", (user_id,))

    async def sync_memory_users_from_qdrant(self, qdrant_url: str, collection_name: str | None = None) -> int:
        """Imports into memory_users the user_ids found in Qdrant.

        Returns the number of newly inserted users.
        Silent if Qdrant is unavailable.
        collection_name defaults to QDRANT_COLLECTION_NAME env var (fallback: "wally_memory").
        """
        import os
        if collection_name is None:
            collection_name = os.getenv("QDRANT_COLLECTION_NAME", "wally_memory")
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=qdrant_url)
            user_ids: set[str] = set()
            offset = None
            while True:
                points, next_offset = await asyncio.to_thread(
                    client.scroll,
                    collection_name=collection_name,
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for point in points:
                    uid = (point.payload or {}).get("user_id")
                    if uid and isinstance(uid, str) and ":" in uid:
                        parts = uid.split(":")
                        # Fix double-prefix (e.g. "discord:discord:123" -> "discord:123")
                        if len(parts) >= 3 and parts[0] == parts[1]:
                            uid = f"{parts[0]}:{':'.join(parts[2:])}"
                            logger.warning("Sync: fixed double-prefix -> {uid}", uid=uid)
                        # Fix cross-platform IDs before adding
                        platform_prefix = uid.split(":")[0]
                        uid, platform_prefix = self._fix_platform(uid, platform_prefix)
                        if platform_prefix:  # skip malformed entries with empty prefix
                            user_ids.add(uid)
                if next_offset is None:
                    break
                offset = next_offset

            inserted = 0
            before = {u["user_id"] for u in await self.list_memory_users()}
            # Ne pas recreer les alias deja lies (sinon ils reapparaissent en double)
            alias_map = await self.get_alias_map()
            alias_ids = set(alias_map.keys())
            for uid in user_ids:
                if uid in alias_ids:
                    continue  # alias lie -- ne pas recreer dans memory_users
                if uid in before:
                    continue  # deja connu -- ne pas ecraser last_updated
                platform = uid.split(":")[0]
                await self.upsert_memory_user(uid, platform, username="")
                inserted += 1

            if inserted:
                logger.info("sync_memory_users_from_qdrant: {n} nouveaux utilisateurs importes", n=inserted)
            return inserted

        except Exception as exc:
            logger.warning("sync_memory_users_from_qdrant echoue: {e}", e=exc)
            return 0

    async def list_memory_users(self, q: str | None = None, include_no_memory: bool = False) -> list[dict]:
        # LEFT JOIN avec trust_scores : la cle memory_users.user_id est "platform:raw_id"
        # alors que trust_scores.user_id est "raw_id" -- on extrait via SUBSTR.
        sql = (
            "SELECT m.user_id, m.platform, m.last_updated, m.username, m.avatar_url, "
            "COALESCE(m.memory_count, 0) AS memory_count, "
            "COALESCE(t.score, 0.0) AS trust_score, 1 AS in_memory_users "
            "FROM memory_users m "
            "LEFT JOIN trust_scores t "
            "  ON t.platform = m.platform "
            "  AND t.user_id = SUBSTR(m.user_id, LENGTH(m.platform) + 2)"
        )
        params: list = []
        if q:
            sql += " WHERE (m.user_id LIKE ? OR m.username LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])

        if include_no_memory:
            # UNION avec trust_scores pour les utilisateurs sans memoire
            union = (
                " UNION ALL "
                "SELECT (t2.platform || ':' || t2.user_id) AS user_id, "
                "t2.platform, t2.updated_at AS last_updated, NULL AS username, "
                "NULL AS avatar_url, 0 AS memory_count, "
                "t2.score AS trust_score, 0 AS in_memory_users "
                "FROM trust_scores t2 "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM memory_users m2 "
                "  WHERE m2.user_id = t2.platform || ':' || t2.user_id"
                ") AND NOT EXISTS ("
                "  SELECT 1 FROM user_links ul "
                "  WHERE ul.alias_id = t2.platform || ':' || t2.user_id "
                "  AND ul.status = 'accepted'"
                ")"
            )
            if q:
                union += " AND (t2.user_id LIKE ? OR t2.platform || ':' || t2.user_id LIKE ?)"
                params.extend([f"%{q}%", f"%{q}%"])
            sql += union

        sql += " ORDER BY in_memory_users DESC, last_updated DESC"
        async with self._conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [
            {
                "user_id": r["user_id"],
                "platform": r["platform"],
                "last_updated": r["last_updated"],
                "username": r["username"],
                "avatar_url": r["avatar_url"] if "avatar_url" in r.keys() else None,
                "memory_count": r["memory_count"],
                "trust_score": round(float(r["trust_score"]), 2),
                "in_memory_users": bool(r["in_memory_users"]),
            }
            for r in rows
        ]

    # ── User links (account linking) ─────────────────────────────────────────

    async def upsert_link_proposal(
        self, canonical_id: str, alias_id: str, confidence: float
    ) -> None:
        """Insere ou met a jour une proposition de liaison (status=pending, update confidence).

        Ne touche pas aux liens deja acceptes ou rejetes -- seules les propositions
        pending voient leur confidence mise a jour.
        """
        async with self._conn.execute(
            """INSERT INTO user_links (canonical_id, alias_id, confidence, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)
               ON CONFLICT(canonical_id, alias_id)
               DO UPDATE SET confidence=excluded.confidence, created_at=excluded.created_at
               WHERE user_links.status = 'pending'""",
            (canonical_id, alias_id, confidence, time.time()),
        ):
            pass
        await self._conn.commit()

    async def list_link_proposals(self, status: str | None = None) -> list[dict]:
        """Retourne les propositions de liaison.

        Chaque dict contient: id, canonical_id, alias_id, confidence, status,
        created_at, resolved_at, canonical_username, alias_username.
        """
        base = (
            "SELECT l.id, l.canonical_id, l.alias_id, l.confidence, l.status, "
            "l.created_at, l.resolved_at, "
            "mc.username AS canonical_username, ma.username AS alias_username "
            "FROM user_links l "
            "LEFT JOIN memory_users mc ON mc.user_id = l.canonical_id "
            "LEFT JOIN memory_users ma ON ma.user_id = l.alias_id"
        )
        if status:
            query = f"{base} WHERE l.status = ? ORDER BY l.confidence DESC"
            cursor = await self._conn.execute(query, (status,))
        else:
            query = f"{base} ORDER BY l.confidence DESC"
            cursor = await self._conn.execute(query)
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "canonical_id": r[1],
                "alias_id": r[2],
                "confidence": r[3],
                "status": r[4],
                "created_at": r[5],
                "resolved_at": r[6],
                "canonical_username": r[7],
                "alias_username": r[8],
            }
            for r in rows
        ]

    async def get_link_proposal(self, link_id: int) -> dict | None:
        """Retourne une proposition de liaison par ID, ou None."""
        base = (
            "SELECT l.id, l.canonical_id, l.alias_id, l.confidence, l.status, "
            "l.created_at, l.resolved_at, "
            "mc.username AS canonical_username, ma.username AS alias_username "
            "FROM user_links l "
            "LEFT JOIN memory_users mc ON mc.user_id = l.canonical_id "
            "LEFT JOIN memory_users ma ON ma.user_id = l.alias_id "
            "WHERE l.id = ?"
        )
        cursor = await self._conn.execute(base, (link_id,))
        r = await cursor.fetchone()
        if r is None:
            return None
        return {
            "id": r[0], "canonical_id": r[1], "alias_id": r[2],
            "confidence": r[3], "status": r[4], "created_at": r[5],
            "resolved_at": r[6], "canonical_username": r[7], "alias_username": r[8],
        }

    async def accept_link(self, link_id: int) -> dict | None:
        """Marque la liaison comme acceptee, retourne canonical_id et alias_id."""
        cursor = await self._conn.execute(
            "UPDATE user_links SET status='accepted', resolved_at=? WHERE id=? RETURNING canonical_id, alias_id",
            (time.time(), link_id),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return {"canonical_id": row[0], "alias_id": row[1]} if row else None

    async def reject_link(self, link_id: int) -> None:
        """Marque la liaison comme rejetee."""
        await self._conn.execute(
            "UPDATE user_links SET status='rejected', resolved_at=? WHERE id=?",
            (time.time(), link_id),
        )
        await self._conn.commit()

    async def get_alias_map(self) -> dict[str, str]:
        """Retourne {alias_id: canonical_id} pour toutes les liaisons acceptees."""
        cursor = await self._conn.execute(
            "SELECT alias_id, canonical_id FROM user_links WHERE status='accepted'"
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

    async def get_platform_users(self, platform: str) -> list[dict]:
        """Retourne les utilisateurs d'une plateforme depuis memory_users.

        Chaque dict contient 'raw_id' (sans prefixe) et 'username' (peut etre None).
        """
        cursor = await self._conn.execute(
            "SELECT user_id, username FROM memory_users WHERE platform = ?",
            (platform,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "raw_id": r[0].split(":", 1)[1] if ":" in r[0] else r[0],
                "username": r[1],
                "full_id": r[0],
            }
            for r in rows
        ]

    # ── User aliases (nickname resolution) ────────────────────────────────────

    async def upsert_alias(
        self,
        nickname: str,
        canonical_uid: str,
        display_name: str,
        source: str,
        confidence: float,
    ) -> None:
        """Insert or update an alias mapping.

        If source == 'llm', an existing alias with source == 'manual' is NOT overwritten.
        """
        nickname = nickname.lower().strip()
        if source == "llm":
            existing = await self.fetch_one(
                "SELECT source FROM user_aliases WHERE nickname = ?", (nickname,)
            )
            if existing and existing["source"] == "manual":
                return  # manual entries are protected from LLM overwrites
        await self.execute(
            "INSERT INTO user_aliases (nickname, canonical_uid, display_name, source, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(nickname) DO UPDATE SET "
            "canonical_uid=excluded.canonical_uid, display_name=excluded.display_name, "
            "source=excluded.source, confidence=excluded.confidence, created_at=excluded.created_at",
            (nickname, canonical_uid, display_name, source, confidence, time.time()),
        )

    async def delete_alias(self, nickname: str) -> None:
        """Delete an alias by nickname."""
        await self.execute(
            "DELETE FROM user_aliases WHERE nickname = ?", (nickname.lower().strip(),)
        )

    async def list_aliases(self, canonical_uid: str | None = None) -> list[dict]:
        """Return all aliases, optionally filtered by canonical_uid."""
        if canonical_uid is not None:
            rows = await self.fetch_all(
                "SELECT nickname, canonical_uid, display_name, source, confidence, created_at "
                "FROM user_aliases WHERE canonical_uid = ? ORDER BY created_at DESC",
                (canonical_uid,),
            )
        else:
            rows = await self.fetch_all(
                "SELECT nickname, canonical_uid, display_name, source, confidence, created_at "
                "FROM user_aliases ORDER BY created_at DESC",
            )
        return [
            {
                "nickname": r["nickname"],
                "canonical_uid": r["canonical_uid"],
                "display_name": r["display_name"],
                "source": r["source"],
                "confidence": float(r["confidence"]),
                "created_at": float(r["created_at"]),
            }
            for r in rows
        ]

    async def get_nickname_alias_map(self) -> dict[str, str]:
        """Return {nickname: canonical_uid} for all aliases."""
        rows = await self.fetch_all(
            "SELECT nickname, canonical_uid FROM user_aliases"
        )
        return {r["nickname"]: r["canonical_uid"] for r in rows}

    async def list_unresolved_aliases(self) -> list[dict]:
        """Return memory_users rows where user_id LIKE 'unknown:%'."""
        rows = await self.fetch_all(
            "SELECT user_id, platform, last_updated, username "
            "FROM memory_users WHERE user_id LIKE 'unknown:%' ORDER BY last_updated DESC",
        )
        return [
            {
                "user_id": r["user_id"],
                "platform": r["platform"],
                "last_updated": float(r["last_updated"]),
                "username": r["username"],
            }
            for r in rows
        ]
