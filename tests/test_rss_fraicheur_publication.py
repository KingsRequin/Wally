"""La fraîcheur d'un article, c'est sa date de PUBLICATION, pas celle de sa lecture.

Mesuré le 2026-08-09 sur la base de prod : 132 des 215 articles `knowledge` — 61 % —
étaient publiés depuis plus de 30 jours et passaient pourtant le filtre de fraîcheur.
Le plus ancien datait du 20 janvier 2025, soit 566 jours. Le filtre portait sur
`fetched_at`, la date à laquelle Wally a lu le flux, et non sur `published_ts`.

Conséquence concrète, avant correctif : à « c'est quoi le dernier patch note d'apex ? »
le recall remontait trois sections du patch du 22 juin — sept semaines — alors que le
patch « Marked » du 3 août était en base. Et à « quoi de neuf sur apex ? », des
articles de février 2025. Le bloc injecté les annonçait comme « les actus les plus
RÉCENTES », sans afficher aucune date : Wally ne pouvait ni le détecter ni le corriger,
et répondait donc faux avec assurance. Un « je sais pas » aurait été moins coûteux.
"""
import time

import pytest

from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables

_JOUR = 86400.0


async def _base(tmp_path) -> Database:
    chemin = str(tmp_path / "rss.db")
    db = await Database.create(chemin)
    await create_v2_tables(chemin)
    return db


async def _article(db, guid, titre, *, role="knowledge", published_ts=None):
    await db.rss_upsert_article(
        feed_name="Apex Patch Notes", role=role, guid=guid, title=titre,
        summary=f"contenu de {titre}", link=f"http://x/{guid}", lang="en",
        published_at=None, published_ts=published_ts,
    )


@pytest.mark.asyncio
async def test_un_article_vieux_lu_hier_nest_pas_frais(tmp_path):
    """Le cas réel : publié il y a 60 jours, récupéré à l'instant."""
    db = await _base(tmp_path)
    maintenant = time.time()
    await _article(db, "vieux", "Ancien patch note", published_ts=maintenant - 60 * _JOUR)
    await _article(db, "recent", "Dernier patch note", published_ts=maintenant - 2 * _JOUR)

    trouves = await db.rss_search_knowledge(
        "patch note", limit=5, max_age_seconds=30 * _JOUR
    )

    titres = [a["title"] for a in trouves]
    assert "Dernier patch note" in titres
    assert "Ancien patch note" not in titres, (
        "un article publié il y a 60 jours est présenté comme récent — c'est le bug "
        "qui faisait raconter le patch de juin quand on demandait celui d'août"
    )


@pytest.mark.asyncio
async def test_sans_date_de_publication_on_retombe_sur_la_lecture(tmp_path):
    """Tous les flux ne datent pas leurs entrées : ne rien exclure à tort."""
    db = await _base(tmp_path)
    await _article(db, "sansdate", "Patch note sans date", published_ts=None)

    trouves = await db.rss_search_knowledge(
        "patch note", limit=5, max_age_seconds=30 * _JOUR
    )
    assert [a["title"] for a in trouves] == ["Patch note sans date"]


@pytest.mark.asyncio
async def test_une_amorce_de_pensee_vieille_nest_pas_proposee(tmp_path):
    """Même défaut côté `stimulus` : penser à une actu de dix-neuf mois comme si
    elle venait de paraître."""
    db = await _base(tmp_path)
    await _article(db, "s_vieux", "Actu de l'an dernier", role="stimulus",
                   published_ts=time.time() - 400 * _JOUR)

    assert await db.rss_peek_stimulus(max_age_seconds=48 * 3600) is None


@pytest.mark.asyncio
async def test_le_bloc_injecte_porte_la_date_de_chaque_article():
    """Sans date affichée, Wally ne peut pas trancher lequel est le plus récent —
    et le bloc lui affirmait un classement chronologique que le tri BM25 ne
    respecte pas."""
    from unittest.mock import AsyncMock, MagicMock

    from bot.discord.handlers import _rss_knowledge_context

    bot = MagicMock()
    bot.config.rss.enabled = True
    bot.config.rss.knowledge_max_age_days = 30
    flux = MagicMock()
    flux.role, flux.enabled = "knowledge", True
    bot.config.rss.feeds = [flux]
    bot.db.rss_search_knowledge_avec_synthese = AsyncMock(return_value=[{
        "title": "Marked Patch Notes — WEAPONS",
        "summary": "Le Nemesis perd 2 dégâts.",
        "link": "http://x/1",
        "published_ts": time.time() - 6 * _JOUR,
    }])

    bloc = await _rss_knowledge_context(bot, "dernier patch note apex ?")

    assert "il y a 6 jours" in bloc, f"aucune date lisible dans le bloc :\n{bloc}"
    # L'ordre est celui de la PERTINENCE (bm25) : ne plus prétendre l'inverse.
    assert "du plus récent au plus ancien" not in bloc
