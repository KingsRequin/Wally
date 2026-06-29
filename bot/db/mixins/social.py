from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import aiosqlite
from loguru import logger

_TZ_DB = ZoneInfo("Europe/Paris")


class SocialMixin:
    _conn: aiosqlite.Connection

    # Declared for type checking (implemented in Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Twitch visits ─────────────────────────────────────────────────────────────

    async def start_twitch_visit(self, channel: str) -> int:
        """Demarre une visite sur une chaine invitee. Retourne l'id de la ligne."""
        now = time.time()
        cursor = await self._conn.execute(
            "INSERT INTO twitch_visits (channel, joined_at) VALUES (?, ?)",
            (channel, now),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def end_twitch_visit(
        self,
        visit_id: int,
        left_at: float,
        msg_count: int,
        summary: str | None,
    ) -> None:
        """Complete une visite avec duree, comptage et resume LLM."""
        joined_at = await self._get_visit_joined_at(visit_id)
        await self._conn.execute(
            "UPDATE twitch_visits SET left_at = ?, duration_s = ?, msg_count = ?, summary = ? WHERE id = ?",
            (left_at, int(left_at - joined_at), msg_count, summary, visit_id),
        )
        await self._conn.commit()

    async def _get_visit_joined_at(self, visit_id: int) -> float:
        """Helper interne : recupere joined_at pour calculer duration_s."""
        row = await self.fetch_one(
            "SELECT joined_at FROM twitch_visits WHERE id = ?", (visit_id,)
        )
        if row is None:
            logger.warning("_get_visit_joined_at: visit_id {id} not found, duration_s will be 0", id=visit_id)
            return time.time()
        return float(row["joined_at"])

    async def get_twitch_visits_for_date(self, date_str: str) -> list[dict]:
        """Retourne les visites dont joined_at tombe dans la journee (Europe/Paris).

        date_str : format YYYY-MM-DD
        """
        from datetime import date as date_type
        target = date_type.fromisoformat(date_str)
        midnight = datetime.combine(target, datetime.min.time(), tzinfo=_TZ_DB).timestamp()
        end = midnight + 86400
        rows = await self.fetch_all(
            "SELECT * FROM twitch_visits WHERE joined_at >= ? AND joined_at < ? ORDER BY joined_at ASC",
            (midnight, end),
        )
        return [dict(row) for row in rows]

    async def get_last_interaction(self, user_id: str) -> float | None:
        """Retourne le timestamp de la derniere interaction d'un utilisateur, ou None."""
        cursor = await self._conn.execute(
            "SELECT last_updated FROM memory_users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return float(row["last_updated"]) if row else None

    async def insert_joke(self, content: str, channel_id: str, platform: str, reaction_count: int) -> None:
        """Stocke une blague reussie."""
        await self.execute(
            "INSERT INTO jokes (content, channel_id, platform, reaction_count, created_at) VALUES (?,?,?,?,?)",
            (content, channel_id, platform, reaction_count, time.time()),
        )

    async def get_recent_jokes(self, channel_id: str, limit: int = 3) -> list[str]:
        """Retourne les dernieres blagues reussies du canal."""
        cursor = await self._conn.execute(
            "SELECT content FROM jokes WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
            (channel_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["content"] for row in rows]

    # ── Topics ────────────────────────────────────────────────────────────────────

    async def upsert_topic(
        self, name: str, summary: str, participants: list[dict], opinion: str
    ) -> None:
        """Insere un sujet ou le fusionne (participants unionnés, mention_count++)."""
        now = time.time()
        cur = await self._conn.execute(
            "SELECT id, participants FROM topics WHERE name=?", (name,)
        )
        row = await cur.fetchone()
        if row is None:
            await self.execute(
                "INSERT INTO topics (name, summary, participants, opinion, "
                "mention_count, last_seen_at, created_at) VALUES (?,?,?,?,?,?,?)",
                (name, summary, json.dumps(participants, ensure_ascii=False),
                 opinion, 1, now, now),
            )
            return
        existing = json.loads(row["participants"] or "[]")
        merged: dict[str, dict] = {}
        for p in existing + participants:
            key = p.get("uid") or p.get("name")
            if key:
                merged[key] = p
        await self.execute(
            "UPDATE topics SET summary=?, participants=?, opinion=?, "
            "mention_count=mention_count+1, last_seen_at=? WHERE id=?",
            (summary, json.dumps(list(merged.values()), ensure_ascii=False),
             opinion, now, row["id"]),
        )

    async def get_topics(self, limit: int = 10) -> list[dict]:
        """Sujets les plus chauds d'abord (récence puis fréquence)."""
        cur = await self._conn.execute(
            "SELECT name, summary, participants, opinion, mention_count, last_seen_at "
            "FROM topics ORDER BY last_seen_at DESC, mention_count DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            {
                "name": r["name"],
                "summary": r["summary"],
                "participants": json.loads(r["participants"] or "[]"),
                "opinion": r["opinion"],
                "mention_count": r["mention_count"],
                "last_seen_at": r["last_seen_at"],
            }
            for r in rows
        ]

    async def cleanup_topics(self, max_age_days: int = 30, max_count: int = 15) -> None:
        """Retire les sujets froids/anciens, garde les max_count plus récents."""
        cutoff = time.time() - max_age_days * 86400
        await self.execute("DELETE FROM topics WHERE last_seen_at < ?", (cutoff,))
        await self.execute(
            "DELETE FROM topics WHERE id NOT IN "
            "(SELECT id FROM topics ORDER BY last_seen_at DESC LIMIT ?)",
            (max_count,),
        )

    # ── Daily log (journal persistence) ──────────────────────────────────────────

    async def log_daily_message(
        self, channel_id: str, author: str, content: str,
        timestamp: float | None = None, platform: str = "discord",
    ) -> None:
        await self.execute(
            "INSERT INTO daily_log (timestamp, channel_id, author, content, platform) VALUES (?, ?, ?, ?, ?)",
            (timestamp if timestamp is not None else time.time(), channel_id, author, content, platform),
        )

    async def get_today_messages(self) -> list[dict]:
        midnight = datetime.now(_TZ_DB).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        rows = await self.fetch_all(
            "SELECT timestamp, channel_id, author, content, platform FROM daily_log "
            "WHERE timestamp >= ? ORDER BY timestamp ASC",
            (midnight,),
        )
        return [
            {
                "timestamp": float(row["timestamp"]),
                "channel_id": row["channel_id"],
                "author": row["author"],
                "content": row["content"],
                "platform": row["platform"] if "platform" in row.keys() else "discord",
            }
            for row in rows
        ]

    async def get_messages_for_date(self, target_date: date) -> list[dict]:
        """Return daily_log messages for a specific date (Europe/Paris)."""
        midnight = datetime.combine(target_date, datetime.min.time(), tzinfo=_TZ_DB).timestamp()
        end = midnight + 86400
        rows = await self.fetch_all(
            "SELECT timestamp, channel_id, author, content, platform FROM daily_log "
            "WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC",
            (midnight, end),
        )
        return [
            {
                "timestamp": float(row["timestamp"]),
                "channel_id": row["channel_id"],
                "author": row["author"],
                "content": row["content"],
                "platform": row["platform"] if "platform" in row.keys() else "discord",
            }
            for row in rows
        ]

    async def cleanup_old_daily_log(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        await self.execute("DELETE FROM daily_log WHERE timestamp < ?", (cutoff,))

    # ── Session persistence ───────────────────────────────────────────────────

    async def insert_session_message(
        self,
        channel_id: str,
        platform: str,
        user_id: str,
        display_name: str,
        content: str,
        timestamp: float,
    ) -> None:
        await self.execute(
            "INSERT INTO session_messages "
            "(channel_id, platform, user_id, display_name, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel_id, platform, user_id, display_name, content, timestamp),
        )

    async def get_recent_session_messages(self, since: float) -> list[dict]:
        """Retourne les messages de session plus recents que `since`."""
        rows = await self.fetch_all(
            "SELECT channel_id, platform, user_id, display_name, content, timestamp "
            "FROM session_messages WHERE timestamp >= ? ORDER BY timestamp ASC",
            (since,),
        )
        return [
            {
                "channel_id": r["channel_id"],
                "platform": r["platform"],
                "user_id": r["user_id"],
                "display_name": r["display_name"],
                "content": r["content"],
                "timestamp": float(r["timestamp"]),
            }
            for r in rows
        ]

    async def delete_session_messages(self, channel_id: str) -> None:
        """Supprime les messages de session d'un canal (apres analyse)."""
        await self.execute(
            "DELETE FROM session_messages WHERE channel_id = ?", (channel_id,)
        )

    async def delete_session_messages_before(self, channel_id: str, cutoff_ts: float) -> None:
        """Delete session messages for a channel older than cutoff_ts."""
        await self.execute(
            "DELETE FROM session_messages WHERE channel_id = ? AND timestamp <= ?",
            (channel_id, cutoff_ts),
        )

    async def insert_session_analysis(
        self, session_id: str, platform: str, channel_id: str, summary: str
    ) -> None:
        """Écrit le résumé de session (upsert par session_id : un seul par canal/jour)."""
        await self.execute(
            "DELETE FROM session_analyses WHERE session_id = ?", (session_id,)
        )
        await self.execute(
            "INSERT INTO session_analyses "
            "(session_id, platform, channel_id, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, platform, channel_id, summary, str(time.time())),
        )

    async def get_recent_session_summaries(
        self, platform: str, channel_id: str, limit: int = 3
    ) -> list[dict]:
        """Retourne les derniers résumés de session d'un canal (recall cross-session)."""
        rows = await self.fetch_all(
            "SELECT summary, created_at FROM session_analyses "
            "WHERE platform = ? AND channel_id = ? AND summary IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (platform, channel_id, limit),
        )
        return [{"summary": r["summary"], "created_at": r["created_at"]} for r in rows]

    # ── Web search log ────────────────────────────────────────────────────────

    async def log_web_search(self, query: str, results_count: int) -> None:
        await self.execute(
            "INSERT INTO web_search_log (timestamp, query, results_count) VALUES (?, ?, ?)",
            (time.time(), query, results_count),
        )

    async def count_web_searches_this_month(self) -> int:
        now = datetime.now(_TZ_DB)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        row = await self.fetch_one(
            "SELECT COUNT(*) AS cnt FROM web_search_log WHERE timestamp >= ?",
            (month_start.timestamp(),),
        )
        return int(row["cnt"]) if row else 0

    # ── Scrape log ──────────────────────────────────────────────────────────

    async def log_scrape(self, url: str) -> None:
        await self.execute(
            "INSERT INTO scrape_log (timestamp, url) VALUES (?, ?)",
            (time.time(), url),
        )

    async def count_scrapes_today(self) -> int:
        now = datetime.now(_TZ_DB)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        row = await self.fetch_one(
            "SELECT COUNT(*) AS cnt FROM scrape_log WHERE timestamp >= ?",
            (day_start.timestamp(),),
        )
        return int(row["cnt"]) if row else 0

    # ── Journal archive ────────────────────────────────────────────────────

    async def insert_journal(self, date: str, content: str, word_count: int, chart_path: str | None = None) -> None:
        await self.execute(
            "INSERT INTO journal_archive (date, content, word_count, created_at, chart_path) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET content=excluded.content, "
            "word_count=excluded.word_count, created_at=excluded.created_at, "
            "chart_path=COALESCE(excluded.chart_path, chart_path)",
            (date, content, word_count, time.time(), chart_path),
        )

    async def get_yesterday_journal(self, today: str | None = None) -> dict | None:
        """Returns yesterday's journal entry, or None if not found.
        today: ISO 8601 date string (YYYY-MM-DD). Defaults to today."""
        if today is None:
            today = datetime.now(_TZ_DB).strftime("%Y-%m-%d")
        from datetime import date as date_type, timedelta
        yesterday = (date_type.fromisoformat(today) - timedelta(days=1)).isoformat()
        row = await self.fetch_one(
            "SELECT date, content, word_count FROM journal_archive WHERE date = ?",
            (yesterday,),
        )
        if row is None:
            return None
        return {"date": row["date"], "content": row["content"], "word_count": int(row["word_count"])}

    async def get_journal_entries(self, limit: int = 30) -> list[dict]:
        """Retourne les N dernieres entrees du journal archive."""
        rows = await self.fetch_all(
            "SELECT date, content, word_count, created_at, chart_path FROM journal_archive ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        result = []
        for row in rows:
            entry = dict(row)
            if entry.get("created_at") and isinstance(entry["created_at"], (int, float)):
                from datetime import datetime, timezone
                entry["created_at"] = datetime.fromtimestamp(entry["created_at"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            result.append(entry)
        return result

    async def get_journals_last_n_days(self, n: int, before_date: str) -> list[dict]:
        """Retourne les n derniers journaux archivés strictement avant before_date,
        ordonnés du plus ancien au plus récent (chronologique).

        before_date : ISO 8601 (YYYY-MM-DD), exclu.
        """
        rows = await self.fetch_all(
            "SELECT date, content, word_count FROM journal_archive "
            "WHERE date < ? ORDER BY date DESC LIMIT ?",
            (before_date, n),
        )
        return [
            {"date": row["date"], "content": row["content"], "word_count": int(row["word_count"])}
            for row in reversed(rows)
        ]
