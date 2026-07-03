"""Service de flux RSS : poll périodique → dédup en base → cognition.

Les articles alimentent deux usages selon le `role` du flux :
- stimulus  : amorce de pensée idle (friction externe quand le chat est calme)
- knowledge : base cherchable, injectée quand le sujet est mentionné

Le service ne fait qu'ingérer/purger. La lecture (amorce, recall) vit dans
`RSSMixin`. Aucune exception réseau/parsing ne remonte : un flux pourri ne doit
jamais casser un tick ni le scheduler.
"""
from __future__ import annotations

import asyncio
import calendar
import html
import re
from datetime import datetime
from typing import TYPE_CHECKING

import feedparser
import httpx
from loguru import logger

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from bot.config import Config, RSSFeedDef
    from bot.db.database import Database

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MAX_ENTRIES_PER_FEED = 40  # garde-fou : on ne traite que la tête du flux
_HTTP_TIMEOUT = 10.0


def _clean_summary(raw: str | None, max_chars: int) -> str:
    """Nettoie un résumé RSS : dé-échappe les entités, retire le HTML, tronque.

    Les full-feeds (Korben) renvoient l'article entier en HTML échappé ; on ne
    veut qu'un extrait lisible pour la cognition."""
    if not raw:
        return ""
    text = html.unescape(raw)          # &lt;p&gt; → <p>
    text = _TAG_RE.sub(" ", text)      # retire les balises
    text = html.unescape(text)         # entités résiduelles (&amp;, &nbsp;…)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


class RSSFeedService:
    def __init__(self, config: "Config", db: "Database"):
        self._config = config
        self._db = db

    @property
    def enabled(self) -> bool:
        return self._config.rss.enabled and bool(self._config.rss.feeds)

    def start(self, scheduler: "AsyncIOScheduler") -> None:
        """Enregistre les jobs de poll et de purge sur le scheduler partagé."""
        if not self.enabled:
            logger.info("RSSFeedService désactivé (aucun flux ou rss.enabled=false)")
            return
        cfg = self._config.rss
        scheduler.add_job(
            self.poll_all, "interval",
            minutes=cfg.poll_interval_minutes,
            next_run_time=datetime.now(),  # premier fetch dès le boot
            id="rss_poll", replace_existing=True, max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            self.purge_old, "interval",
            hours=6,
            id="rss_purge", replace_existing=True, max_instances=1,
            coalesce=True,
        )
        logger.info(
            "RSSFeedService planifié ({n} flux, toutes les {m} min)",
            n=len(cfg.feeds), m=cfg.poll_interval_minutes,
        )

    async def poll_all(self) -> int:
        """Poll tous les flux actifs. Retourne le nombre d'articles nouveaux."""
        total_new = 0
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; WallyBot RSS)"},
        ) as client:
            for feed in self._config.rss.feeds:
                if not feed.enabled:
                    continue
                try:
                    total_new += await self._poll_feed(client, feed)
                except Exception as exc:  # flux pourri / réseau : on log et on continue
                    logger.warning("Flux RSS '{n}' en échec : {e}", n=feed.name, e=exc)
        if total_new:
            logger.info("RSS : {n} nouveaux articles ingérés", n=total_new)
        return total_new

    async def _poll_feed(self, client: httpx.AsyncClient, feed: "RSSFeedDef") -> int:
        resp = await client.get(feed.url)
        resp.raise_for_status()
        # feedparser est synchrone (parsing + normalisation) → hors event loop.
        parsed = await asyncio.to_thread(feedparser.parse, resp.text)
        cfg = self._config.rss
        new = 0
        for entry in parsed.entries[:_MAX_ENTRIES_PER_FEED]:
            guid = entry.get("id") or entry.get("link") or ""
            title = (entry.get("title") or "").strip()
            if not guid or not title:
                continue
            summary = _clean_summary(
                entry.get("summary") or entry.get("description"),
                cfg.summary_max_chars,
            )
            # Date de publication en epoch (triable) : feedparser normalise en
            # struct_time UTC. Sert à remonter l'actu la plus récente au recall.
            tstruct = entry.get("published_parsed") or entry.get("updated_parsed")
            published_ts = calendar.timegm(tstruct) if tstruct else None
            inserted = await self._db.rss_upsert_article(
                feed_name=feed.name,
                role=feed.role,
                guid=guid,
                title=title,
                summary=summary,
                link=entry.get("link") or "",
                lang=feed.lang,
                published_at=entry.get("published") or entry.get("updated") or None,
                published_ts=published_ts,
            )
            if inserted:
                new += 1
        return new

    async def purge_old(self) -> int:
        return await self._db.rss_purge_old(
            retention_seconds=self._config.rss.retention_days * 86400
        )
