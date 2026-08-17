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
            # Même correctif que `rss_search_knowledge` : la fraîcheur se mesure à la
            # publication. Sans ça, un flux qui ressort un vieil article le donnait
            # comme amorce de pensée, et Wally se mettait à réfléchir à une actu de
            # dix-neuf mois comme si elle venait de paraître.
            "WHERE role = 'stimulus' AND injected_at IS NULL "
            "AND COALESCE(published_ts, fetched_at) >= ? "
            "ORDER BY COALESCE(published_ts, fetched_at) DESC, id DESC LIMIT 1",
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
        self, query: str, *, limit: int = 3, max_age_seconds: float
    ) -> list[dict]:
        """Articles `knowledge` frais qui matchent le sujet, les plus PERTINENTS
        d'abord (n'affecte pas injected_at).

        Le classement était la récence seule, ce qui se défendait pour un flux
        d'actualités : un article y est un sujet, et le plus frais est le bon.
        Ça ne tient plus depuis qu'un patch note entre découpé en sections —
        elles partagent toutes une seule date, la récence ne départage donc plus
        rien, et une annonce promotionnelle publiée le même jour passait devant
        la section technique cherchée.

        `bm25` classe donc en premier (plus petit = plus pertinent), la récence
        ne servant qu'à départager deux passages également pertinents."""
        match = _fts_or_query(query)
        if not match:
            return []
        cutoff = time.time() - max_age_seconds
        rows = await self.fetch_all(
            "SELECT a.* FROM rss_articles a "
            "JOIN rss_articles_fts f ON f.rowid = a.id "
            # Fraîcheur = date de PUBLICATION, pas date de lecture. Sur `fetched_at`,
            # 132 des 215 articles de la base de prod passaient le filtre de 30 jours
            # alors qu'ils étaient publiés depuis plus longtemps — le plus ancien
            # depuis 566 jours. « Le dernier patch note » remontait alors celui du
            # 22 juin quand celui du 3 août était en base.
            "WHERE a.role = 'knowledge' AND COALESCE(a.published_ts, a.fetched_at) >= ? "
            "AND rss_articles_fts MATCH ? "
            "ORDER BY bm25(rss_articles_fts), "
            "COALESCE(a.published_ts, a.fetched_at) DESC LIMIT ?",
            (cutoff, match, limit),
        )
        return [dict(r) for r in rows]

    async def rss_dernier_knowledge_ts(self) -> float | None:
        """Quand date le patch note le plus récent CONNU, ou None.

        C'est l'ancre de sa connaissance, et elle manquait. Sans elle, « rien
        n'a changé depuis » est indémontrable : Wally ne sait pas s'il n'a rien
        vu parce qu'il n'y a rien eu, ou parce que sa base s'arrête là. Il
        présentait donc le dernier changement qu'il connaissait comme le
        dernier survenu — un patch de deux mois annoncé « récent ».

        Sans borne d'âge, volontairement : l'ancre doit dire la vérité même
        quand le jeu n'a rien publié depuis longtemps. C'est justement ce
        silence-là qui est la réponse.
        """
        row = await self.fetch_one(
            "SELECT MAX(COALESCE(published_ts, fetched_at)) AS ts "
            "FROM rss_articles WHERE role = 'knowledge'"
        )
        ts = (dict(row).get("ts") if row else None)
        return float(ts) if ts else None

    async def rss_derniere_synthese(self, *, max_age_seconds: float) -> dict | None:
        """La section de SYNTHÈSE de patch la plus récente, ou None.

        Un patch note Steam arrive découpé — jusqu'à 39 sections pour un seul patch
        sur la base de prod. Il porte ses propres sections de vue d'ensemble (`INTRO`,
        `Designer's Notes — TL;DR`), mais leur titre ne contient aucun mot rare : BM25
        ne les distingue de rien, et « c'est quoi le dernier patch note ? » repartait
        avec LOBA, WEAPONS et Map Rotations — trois détails, aucune synthèse.
        """
        cutoff = time.time() - max_age_seconds
        row = await self.fetch_one(
            "SELECT * FROM rss_articles WHERE role = 'knowledge' "
            "AND COALESCE(published_ts, fetched_at) >= ? "
            "AND (title LIKE '%INTRO%' OR title LIKE '%TL;DR%') "
            "ORDER BY COALESCE(published_ts, fetched_at) DESC LIMIT 1",
            (cutoff,),
        )
        return dict(row) if row else None

    async def rss_search_knowledge_avec_synthese(
        self, query: str, *, limit: int = 3, max_age_seconds: float
    ) -> list[dict]:
        """`rss_search_knowledge`, plus la garantie d'une vue d'ensemble du patch.

        Aucune détection d'intention : distinguer une question « générale » d'une
        question « ciblée » se devine mal, et connaître le patch courant sert dans les
        deux cas — savoir de quel patch on parle aide même à répondre sur une arme.
        La synthèse n'est ajoutée que si la pertinence ne l'a pas déjà remontée.
        """
        articles = await self.rss_search_knowledge(
            query, limit=limit, max_age_seconds=max_age_seconds
        )
        synthese = await self.rss_derniere_synthese(max_age_seconds=max_age_seconds)
        if synthese and synthese["id"] not in {a["id"] for a in articles}:
            articles.append(synthese)
        return articles

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
