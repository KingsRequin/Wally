"""À une question générale, il faut la SYNTHÈSE du patch, pas trois détails.

Un patch note Steam entre découpé en sections : 215 sections pour 80 posts sur la
base de prod, jusqu'à 39 sections pour un seul patch. Le recall en remonte trois,
classées par pertinence lexicale — à « c'est quoi le dernier patch note d'apex ? » il
recevait donc LOBA, WEAPONS et Map Rotations. Trois détails, aucune vue d'ensemble.

Or les patch notes portent leurs propres sections de synthèse : `— INTRO`,
`Designer's Notes — TL;DR`. Elles existent exactement pour ça, et le tri BM25 ne les
privilégiait pas : leur titre ne contient aucun mot rare, donc rien ne les distingue.

On garantit donc la présence de la synthèse la plus récente, en plus des résultats
pertinents. Pas de détection d'intention — « générale » ou « ciblée » se devine mal,
et connaître le patch courant sert dans les deux cas.
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


async def _section(db, guid, titre, *, jours):
    await db.rss_upsert_article(
        feed_name="Apex Patch Notes", role="knowledge", guid=guid, title=titre,
        summary=f"détail de {titre}", link=f"http://x/{guid}", lang="en",
        published_at=None, published_ts=time.time() - jours * _JOUR,
    )


@pytest.mark.asyncio
async def test_la_synthese_du_dernier_patch_est_toujours_remontee(tmp_path):
    db = await _base(tmp_path)
    # Le patch récent et ses sections de détail, plus sa synthèse.
    await _section(db, "s1", "Marked Patch Notes — LOBA", jours=6)
    await _section(db, "s2", "Marked Patch Notes — WEAPONS", jours=6)
    await _section(db, "s3", "Marked Patch Notes — Map Rotations", jours=6)
    await _section(db, "s4", "Marked Patch Notes — INTRO", jours=6)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "c'est quoi le dernier patch note", limit=3, max_age_seconds=90 * _JOUR
    )

    titres = [a["title"] for a in trouves]
    assert any("INTRO" in t for t in titres), (
        f"aucune vue d'ensemble du patch dans le lot : {titres}"
    )


@pytest.mark.asyncio
async def test_la_synthese_nest_pas_dupliquee(tmp_path):
    """Si la pertinence l'a déjà remontée, ne pas la compter deux fois."""
    db = await _base(tmp_path)
    await _section(db, "s1", "Marked Patch Notes — INTRO", jours=6)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "patch note intro", limit=3, max_age_seconds=90 * _JOUR
    )
    assert len(trouves) == len({a["id"] for a in trouves})
    assert len(trouves) == 1


@pytest.mark.asyncio
async def test_la_synthese_la_plus_recente_gagne(tmp_path):
    """Deux patchs dans la fenêtre : c'est la synthèse du plus récent qui compte."""
    db = await _base(tmp_path)
    await _section(db, "vieux", "Overclocked Patch Notes — INTRO", jours=48)
    await _section(db, "recent", "Marked Patch Notes — INTRO", jours=6)
    await _section(db, "detail", "Marked Patch Notes — WEAPONS", jours=6)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "nerf arme", limit=2, max_age_seconds=90 * _JOUR
    )
    syntheses = [a["title"] for a in trouves if "INTRO" in a["title"]]
    assert syntheses == ["Marked Patch Notes — INTRO"]


@pytest.mark.asyncio
async def test_sans_synthese_en_base_rien_ne_casse(tmp_path):
    db = await _base(tmp_path)
    await _section(db, "s1", "Marked Patch Notes — LOBA", jours=6)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "loba", limit=3, max_age_seconds=90 * _JOUR
    )
    assert [a["title"] for a in trouves] == ["Marked Patch Notes — LOBA"]


@pytest.mark.asyncio
async def test_une_synthese_hors_fenetre_nest_pas_remontee(tmp_path):
    """La garantie ne doit pas contourner le filtre de fraîcheur."""
    db = await _base(tmp_path)
    await _section(db, "s1", "Marked Patch Notes — LOBA", jours=6)
    await _section(db, "vieux", "Saison 20 Patch Notes — INTRO", jours=200)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "loba", limit=3, max_age_seconds=90 * _JOUR
    )
    assert not any("Saison 20" in a["title"] for a in trouves)
