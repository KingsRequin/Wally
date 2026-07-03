from types import SimpleNamespace

import pytest

from bot.config import RSSFeedsConfig, RSSFeedDef
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables
from bot.discord.handlers import _rss_knowledge_context


async def _make_db(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


def _bot(db, feeds=None):
    if feeds is None:
        feeds = [RSSFeedDef(name="Dexerto Apex", url="u", role="knowledge", lang="en")]
    return SimpleNamespace(config=SimpleNamespace(rss=RSSFeedsConfig(feeds=feeds)), db=db)


async def _add_knowledge(db, **over):
    base = dict(feed_name="Dexerto Apex", role="knowledge", guid="k1",
                title="Apex Legends Season 29 patch notes",
                summary="new legend Axle, buffs and nerfs",
                link="https://dex/apex-29", lang="en", published_at=None)
    base.update(over)
    await db.rss_upsert_article(**base)


@pytest.mark.asyncio
async def test_recall_injects_citation_marker(tmp_path):
    db = await _make_db(tmp_path)
    await _add_knowledge(db)
    out = await _rss_knowledge_context(_bot(db), "c'est quoi la dernière maj d'Apex ?")
    assert out is not None
    assert "[¹](<https://dex/apex-29>)" in out   # marqueur cliquable prêt à coller
    assert "Season 29" in out
    await db.close()


@pytest.mark.asyncio
async def test_recall_no_match_returns_none(tmp_path):
    db = await _make_db(tmp_path)
    await _add_knowledge(db)
    assert await _rss_knowledge_context(_bot(db), "je mange une pizza margherita") is None
    await db.close()


@pytest.mark.asyncio
async def test_recall_disabled_and_no_knowledge_feed(tmp_path):
    db = await _make_db(tmp_path)
    await _add_knowledge(db, title="Apex maj", guid="k")
    bot_off = _bot(db)
    bot_off.config.rss.enabled = False
    assert await _rss_knowledge_context(bot_off, "Apex maj patch") is None

    bot_stim = _bot(db, feeds=[RSSFeedDef(name="Korben", url="u", role="stimulus", lang="fr")])
    assert await _rss_knowledge_context(bot_stim, "Apex maj patch") is None
    await db.close()


@pytest.mark.asyncio
async def test_recall_ignores_stimulus_articles(tmp_path):
    db = await _make_db(tmp_path)
    # Article Apex mais en rôle stimulus → le recall knowledge ne doit pas le voir.
    await db.rss_upsert_article(feed_name="JVC", role="stimulus", guid="s",
                                title="Apex nouveau patch", summary="s",
                                link="u", lang="fr", published_at=None)
    assert await _rss_knowledge_context(_bot(db), "Apex patch nouveau") is None
    await db.close()


@pytest.mark.asyncio
async def test_recall_short_message_ignored(tmp_path):
    db = await _make_db(tmp_path)
    await _add_knowledge(db)
    assert await _rss_knowledge_context(_bot(db), "ok") is None
    await db.close()
