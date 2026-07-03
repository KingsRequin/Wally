import time

import pytest

from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables


async def _make_db(tmp_path):
    path = str(tmp_path / "t.db")
    db = await Database.create(path)
    await create_v2_tables(path)
    return db


async def _add(db, *, feed="JeuxVideo.com", role="stimulus", guid="g1",
               title="Titre", summary="résumé", link="http://x", lang="fr", published=None):
    return await db.rss_upsert_article(
        feed_name=feed, role=role, guid=guid, title=title, summary=summary,
        link=link, lang=lang, published_at=published,
    )


@pytest.mark.asyncio
async def test_upsert_dedup(tmp_path):
    db = await _make_db(tmp_path)
    assert await _add(db, guid="a") is True
    # Même (feed, guid) → ignoré
    assert await _add(db, guid="a", title="autre titre") is False
    # Même guid mais autre flux → nouvel article
    assert await _add(db, feed="Korben", guid="a") is True
    await db.close()


@pytest.mark.asyncio
async def test_next_stimulus_marks_injected(tmp_path):
    db = await _make_db(tmp_path)
    await _add(db, guid="a", title="Article A")
    first = await db.rss_next_stimulus(max_age_seconds=3600)
    assert first is not None and first["title"] == "Article A"
    assert first["injected_at"] is None  # snapshot avant marquage
    # Réinjection impossible : déjà vu
    assert await db.rss_next_stimulus(max_age_seconds=3600) is None
    await db.close()


@pytest.mark.asyncio
async def test_next_stimulus_respects_freshness_and_role(tmp_path):
    db = await _make_db(tmp_path)
    await _add(db, role="knowledge", guid="k")   # mauvais rôle → jamais piochE
    assert await db.rss_next_stimulus(max_age_seconds=3600) is None
    await _add(db, role="stimulus", guid="s")
    # Fenêtre de fraîcheur nulle → rien d'assez récent
    assert await db.rss_next_stimulus(max_age_seconds=0) is None
    assert await db.rss_next_stimulus(max_age_seconds=3600) is not None
    await db.close()


@pytest.mark.asyncio
async def test_search_knowledge_fts(tmp_path):
    db = await _make_db(tmp_path)
    await _add(db, role="knowledge", guid="k1",
               title="Nouveau patch Apex Legends saison 29", summary="buffs et nerfs des légendes")
    await _add(db, role="knowledge", guid="k2",
               title="Sortie de Zelda", summary="nouvelle aventure Nintendo")
    hits = await db.rss_search_knowledge("c'est quoi la dernière maj Apex ?",
                                         limit=2, max_age_seconds=86400)
    assert len(hits) == 1
    assert hits[0]["guid"] == "k1"
    # Stimulus non concerné par le recall knowledge
    await _add(db, role="stimulus", guid="s1", title="Apex tournoi")
    hits2 = await db.rss_search_knowledge("Apex", limit=5, max_age_seconds=86400)
    assert {h["guid"] for h in hits2} == {"k1"}
    await db.close()


@pytest.mark.asyncio
async def test_search_knowledge_empty_query(tmp_path):
    db = await _make_db(tmp_path)
    await _add(db, role="knowledge", guid="k1", title="Apex")
    # Requête sans token exploitable (≥3 lettres) → pas de crash FTS, liste vide
    assert await db.rss_search_knowledge("!! ?? a", limit=2, max_age_seconds=86400) == []
    await db.close()


@pytest.mark.asyncio
async def test_purge_old(tmp_path):
    db = await _make_db(tmp_path)
    await _add(db, guid="fresh")
    await _add(db, guid="stale")
    # Vieillit artificiellement "stale"
    await db.execute(
        "UPDATE rss_articles SET fetched_at = ? WHERE guid = 'stale'",
        (time.time() - 10 * 86400,),
    )
    deleted = await db.rss_purge_old(retention_seconds=7 * 86400)
    assert deleted == 1
    remaining = await db.fetch_all("SELECT guid FROM rss_articles")
    assert {r["guid"] for r in remaining} == {"fresh"}
    # Le FTS a suivi la suppression (trigger _ad)
    fts = await db.fetch_all("SELECT rowid FROM rss_articles_fts")
    assert len(fts) == 1
    await db.close()


def test_rss_config_defaults():
    from bot.config import RSSFeedsConfig

    # Défauts : 3 flux (JVC + Korben en stimulus, Dexerto en knowledge)
    roles = {f.name: f.role for f in RSSFeedsConfig().feeds}
    assert roles["JeuxVideo.com"] == "stimulus"
    assert roles["Korben"] == "stimulus"
    assert roles["Dexerto Apex"] == "knowledge"


def test_config_rss_roundtrip(tmp_path):
    """Sur une base de config réelle : absence de section `rss:` → défauts,
    puis save()/load() préserve une config RSS personnalisée."""
    import shutil
    from bot.config import Config, RSSFeedDef

    base = tmp_path / "config.yaml"
    shutil.copy("config.example.yaml", base)

    loaded = Config.load(str(base))
    # config.example.yaml n'a pas de section rss → on retombe sur les défauts
    assert len(loaded.rss.feeds) == 3

    # Personnalise, sauvegarde, recharge
    loaded.rss.poll_interval_minutes = 15
    loaded.rss.feeds = [RSSFeedDef(name="Test", url="http://t", role="knowledge", lang="en")]
    loaded.save()

    reloaded = Config.load(str(base))
    assert reloaded.rss.poll_interval_minutes == 15
    assert len(reloaded.rss.feeds) == 1
    assert isinstance(reloaded.rss.feeds[0], RSSFeedDef)
    assert reloaded.rss.feeds[0].role == "knowledge"
    assert reloaded.rss.feeds[0].name == "Test"
