from types import SimpleNamespace

import pytest

from bot.config import RSSFeedsConfig, RSSFeedDef
from bot.core.rss_feed import RSSFeedService, _clean_summary
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Flux test</title>
<item>
  <title>Article Un</title><link>http://x/1</link><guid>http://x/1</guid>
  <description>&lt;p&gt;Bonjour &lt;b&gt;monde&lt;/b&gt;&amp;nbsp;!&lt;/p&gt;</description>
  <pubDate>Fri, 03 Jul 2026 00:00:00 +0000</pubDate>
</item>
<item>
  <title>Article Deux</title><link>http://x/2</link><guid>http://x/2</guid>
  <description>résumé deux</description>
</item>
</channel></rss>"""


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, text):
        self._text = text

    async def get(self, url):
        return _FakeResp(self._text)


class _CtxClient:
    """Faux httpx.AsyncClient utilisable comme context manager async."""
    def __init__(self, text=None, boom=False):
        self._text = text
        self._boom = boom

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if self._boom:
            raise RuntimeError("network down")
        return _FakeResp(self._text)


async def _make_db(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


def _cfg(**over):
    feeds = over.pop("feeds", [RSSFeedDef(name="F", url="http://x/feed", role="stimulus", lang="fr")])
    return SimpleNamespace(rss=RSSFeedsConfig(feeds=feeds, **over))


def test_clean_summary_strips_html_and_truncates():
    out = _clean_summary("&lt;p&gt;Bonjour &lt;b&gt;monde&lt;/b&gt;&amp;nbsp;!&lt;/p&gt;", 100)
    assert "<" not in out and ">" not in out
    assert "Bonjour monde" in out
    long = _clean_summary("a" * 500, 50)
    assert len(long) <= 51 and long.endswith("…")


def test_clean_summary_empty():
    assert _clean_summary(None, 100) == ""
    assert _clean_summary("", 100) == ""


def test_enabled_property():
    assert RSSFeedService(_cfg(), None).enabled is True
    assert RSSFeedService(_cfg(enabled=False), None).enabled is False
    assert RSSFeedService(_cfg(feeds=[]), None).enabled is False


@pytest.mark.asyncio
async def test_poll_feed_ingests_and_dedups(tmp_path):
    db = await _make_db(tmp_path)
    svc = RSSFeedService(_cfg(), db)
    feed = svc._config.rss.feeds[0]
    client = _FakeClient(RSS_SAMPLE)

    assert await svc._poll_feed(client, feed) == 2
    # 2e passage : mêmes guid → aucun nouveau (dédup)
    assert await svc._poll_feed(client, feed) == 0

    rows = await db.fetch_all("SELECT title, summary, role FROM rss_articles ORDER BY guid")
    assert [r["title"] for r in rows] == ["Article Un", "Article Deux"]
    assert "<" not in rows[0]["summary"]          # HTML nettoyé
    assert "Bonjour monde" in rows[0]["summary"]
    assert rows[0]["role"] == "stimulus"          # rôle du flux propagé
    await db.close()


@pytest.mark.asyncio
async def test_poll_all_success(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    svc = RSSFeedService(_cfg(), db)
    monkeypatch.setattr("bot.core.rss_feed.httpx.AsyncClient",
                        lambda **kw: _CtxClient(text=RSS_SAMPLE))
    assert await svc.poll_all() == 2
    await db.close()


@pytest.mark.asyncio
async def test_poll_all_swallows_feed_errors(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    svc = RSSFeedService(_cfg(), db)
    monkeypatch.setattr("bot.core.rss_feed.httpx.AsyncClient",
                        lambda **kw: _CtxClient(boom=True))
    # Un flux qui plante ne doit pas remonter d'exception ni casser le scheduler.
    assert await svc.poll_all() == 0
    await db.close()


@pytest.mark.asyncio
async def test_purge_old_delegates(tmp_path):
    db = await _make_db(tmp_path)
    svc = RSSFeedService(_cfg(retention_days=7), db)
    await db.rss_upsert_article(feed_name="F", role="stimulus", guid="g", title="t",
                                summary="s", link="l", lang="fr", published_at=None)
    await db.execute("UPDATE rss_articles SET fetched_at = fetched_at - ?", (30 * 86400,))
    assert await svc.purge_old() == 1
    await db.close()
