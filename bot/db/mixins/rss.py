from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass


def _fts_or_query(text: str) -> str:
    """Transforme un texte libre en requête FTS5 sûre (tokens ≥3 en OR).

    Neutralise la syntaxe FTS (opérateurs, guillemets) en ne gardant que les
    mots alphanumériques, chacun cité, joints par OR. Retourne "" si rien
    d'exploitable (l'appelant court-circuite alors la recherche)."""
    terms = [t for t in re.findall(r"\w+", text.lower()) if len(t) >= 3]
    return " OR ".join(f'"{t}"' for t in terms)


class RSSMixin:
    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database)
    async def fetch_all(self, query: str, params=()) -> list: ...
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...

    # ── Ingestion / dédup ─────────────────────────────────────────────────────

    async def rss_upsert_article(
        self,
        *,
        feed_name: str,
        role: str,
        guid: str,
        title: str,
        summary: str | None,
        link: str | None,
        lang: str,
        published_at: str | None,
        published_ts: float | None = None,
    ) -> bool:
        """Insère un article s'il est nouveau. Retourne True si nouvellement
        inséré, False si déjà connu (dédup via UNIQUE(feed_name, guid)).

        `published_ts` = date de publication en epoch (triable), pour remonter
        les actus les plus récentes en premier au recall knowledge."""
        async with self._conn.execute(
            "INSERT OR IGNORE INTO rss_articles "
            "(feed_name, role, guid, title, summary, link, lang, published_at, published_ts, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (feed_name, role, guid, title, summary, link, lang, published_at, published_ts, time.time()),
        ) as cursor:
            inserted = cursor.rowcount > 0
        await self._conn.commit()
        return inserted

    # ── Stimulus (amorce de pensée idle) ──────────────────────────────────────

    async def rss_peek_stimulus(self, *, max_age_seconds: float) -> dict | None:
        """Retourne l'article `stimulus` frais le plus récent jamais injecté,
        SANS le marquer. Permet de ne le consommer que s'il est réellement
        retenu comme amorce (sinon on brûlerait des articles jamais montrés)."""
        cutoff = time.time() - max_age_seconds
        row = await self.fetch_one(
            "SELECT * FROM rss_articles "
            "WHERE role = 'stimulus' AND injected_at IS NULL AND fetched_at >= ? "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (cutoff,),
        )
        return dict(row) if row else None

    async def rss_mark_injected(self, article_id: int) -> None:
        """Marque un article comme ayant traversé les pensées (dédup stimulus)."""
        await self.execute(
            "UPDATE rss_articles SET injected_at = ? WHERE id = ?",
            (time.time(), article_id),
        )

    async def rss_next_stimulus(self, *, max_age_seconds: float) -> dict | None:
        """Peek + marque atomiquement (pioche l'article et le consomme)."""
        article = await self.rss_peek_stimulus(max_age_seconds=max_age_seconds)
        if article:
            await self.rss_mark_injected(article["id"])
        return article

    # ── Knowledge (recall contextuel via FTS) ─────────────────────────────────

    async def rss_search_knowledge(
        self, query: str, *, limit: int = 2, max_age_seconds: float
    ) -> list[dict]:
        """Recherche BM25 dans les articles `knowledge` frais qui matchent la
        requête. Retourne les plus pertinents (n'affecte pas injected_at)."""
        match = _fts_or_query(query)
        if not match:
            return []
        cutoff = time.time() - max_age_seconds
        # Hybride pertinence + fraîcheur : on prend d'abord le pool des plus
        # PERTINENTS (bm25) — ça écarte les articles hors-sujet qui ne partagent
        # qu'un mot — puis parmi eux on remonte les plus RÉCENTS. Pour « dernier
        # patch note », on veut le patch note le plus récent, pas la news la plus
        # récente qui mentionne juste « apex ». published_ts absent → fallback.
        pool = max(limit * 4, 8)
        rows = await self.fetch_all(
            "SELECT * FROM ("
            "  SELECT a.*, bm25(rss_articles_fts) AS _rank "
            "  FROM rss_articles a "
            "  JOIN rss_articles_fts f ON f.rowid = a.id "
            "  WHERE a.role = 'knowledge' AND a.fetched_at >= ? "
            "  AND rss_articles_fts MATCH ? "
            "  ORDER BY _rank LIMIT ?"
            ") ORDER BY COALESCE(published_ts, fetched_at) DESC LIMIT ?",
            (cutoff, match, pool, limit),
        )
        return [dict(r) for r in rows]

    # ── Purge (rétention) ─────────────────────────────────────────────────────

    async def rss_purge_old(self, *, retention_seconds: float) -> int:
        """Supprime les articles plus vieux que la fenêtre de rétention.
        Retourne le nombre de lignes supprimées."""
        cutoff = time.time() - retention_seconds
        async with self._conn.execute(
            "DELETE FROM rss_articles WHERE fetched_at < ?", (cutoff,)
        ) as cursor:
            deleted = cursor.rowcount
        await self._conn.commit()
        return deleted
