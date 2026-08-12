from types import SimpleNamespace

import pytest

from bot.config import RSSFeedsConfig, RSSFeedDef
from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables
from bot.discord.handlers import _rss_knowledge_context, _is_news_query


def test_is_news_query():
    # Questions d'actu → True (les outils de lookup seront coupés)
    for q in ["donne moi les dernières actus d'apex ?", "quoi de neuf sur Apex ?",
              "la nouvelle mise à jour Apex", "c'est quoi le dernier patch ?",
              "des nouveautés cette semaine ?", "la roadmap Apex"]:
        assert _is_news_query(q), q
    # Questions hors-actu → False (apex_legends reste dispo pour rang/stats)
    for q in ["c'est quoi mon rang apex ?", "tu joues à quoi ?", "salut ça va ?"]:
        assert not _is_news_query(q), q


def test_dernier_tout_seul_ne_fait_pas_une_question_d_actu():
    """Vécu le 2026-08-12 : « donne la courbe de kill de azra du dernier stream ».

    Le fragment « derni » visait « les dernières actus » et « le dernier
    patch » — mais « dernier » est un mot ordinaire. Il coupait les outils de
    lookup sur des demandes qui n'ont rien d'une question d'actualité. Les vraies
    questions d'actu portent toutes un autre marqueur (news, patch, maj…).
    """
    for q in ["donne la courbe de kill de azra du dernier stream",
              "la dernière fois que azra a joué",
              "montre le dernier clip",
              "il a fait combien de kills sur les 10 dernières minutes ?",
              "il a fait neuf kills sur la partie"]:
        assert not _is_news_query(q), q


def test_apex_legends_n_est_pas_un_outil_de_lookup():
    """Le recall RSS couvre les patch notes et les articles. `apex_legends` ne
    rend que de la donnée de jeu en direct — rang, stats, progression, rotation
    de map, statut des serveurs. Les deux ne se recoupent JAMAIS, donc le recall
    ne peut pas se substituer à l'outil.

    Le 2026-08-12, il était coupé de l'offre en même temps que `web_search` :
    le refus de `show_apex` renvoyait alors vers un outil que le modèle n'avait
    plus, et Wally a promis une courbe qu'il ne pouvait plus produire.
    """
    from bot.discord.handlers import _LOOKUP_TOOLS

    assert "apex_legends" not in _LOOKUP_TOOLS


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
