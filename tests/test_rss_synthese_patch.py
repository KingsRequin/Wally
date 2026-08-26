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
    """Deux patchs dans la fenêtre : c'est la synthèse du plus récent qui compte.

    La requête doit MATCHER : la synthèse complète un recall, elle ne le
    déclenche pas. « nerf arme » ne touchait aucun de ces trois articles, et
    le test ne tenait que parce que la synthèse s'ajoutait même à un résultat
    vide — c'est-à-dire à CHAQUE message d'au moins quatre caractères, dont
    « je mange une pizza ». Ce bruit permanent est ce que l'owner a fini par
    voir : un patch de trois semaines présenté comme l'actualité.
    """
    db = await _base(tmp_path)
    await _section(db, "vieux", "Overclocked Patch Notes — INTRO", jours=48)
    await _section(db, "recent", "Marked Patch Notes — INTRO", jours=6)
    await _section(db, "detail", "Marked Patch Notes — WEAPONS", jours=6)

    trouves = await db.rss_search_knowledge_avec_synthese(
        "weapons", limit=2, max_age_seconds=90 * _JOUR
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


# ── mais « la synthèse » doit être celle du DERNIER patch ───────────────
#
# Constaté en prod le 2026-08-26 par l'owner : « les patch notes Apex ne sont
# toujours pas donnés au plus récent ». La base contenait pourtant la mise à
# jour du 25/08 — c'est le recall qui servait l'INTRO du 3 août.
#
# La cause : chercher « la dernière section qui s'appelle INTRO » n'est pas
# chercher « la vue d'ensemble du dernier patch ». Seuls les gros patchs de
# saison portent une section INTRO ; les mises à jour intermédiaires — donc
# les PLUS RÉCENTES — n'en ont pas, et ne pouvaient jamais être remontées.
@pytest.mark.asyncio
async def test_la_synthese_suit_le_dernier_patch_meme_sans_section_INTRO(tmp_path):
    db = await _base(tmp_path)
    # Le gros patch de saison, trois semaines plus tôt : il a son INTRO.
    await _section(db, "111#0", "Marked Patch Notes — INTRO", jours=23)
    await _section(db, "111#1", "Marked Patch Notes — LOBA", jours=23)
    # La mise à jour d'hier : une seule section, sans INTRO ni TL;DR. C'est la
    # forme réelle de « Apex Legends: Latest Update 8/25/2026 » en production.
    await _section(db, "222#0", "Apex Legends: Latest Update 8/25/2026", jours=1)

    synthese = await db.rss_derniere_synthese(max_age_seconds=100 * _JOUR)

    assert synthese is not None
    assert "8/25/2026" in synthese["title"], (
        f"le recall sert un patch périmé : {synthese['title']}"
    )


@pytest.mark.asyncio
async def test_quand_le_dernier_patch_A_une_intro_c_est_elle_qu_on_prend(tmp_path):
    """La vue d'ensemble reste préférée — dans le bon patch, cette fois."""
    db = await _base(tmp_path)
    await _section(db, "333#0", "Nouveau patch — WEAPONS", jours=1)
    await _section(db, "333#1", "Nouveau patch — INTRO", jours=1)
    await _section(db, "333#2", "Nouveau patch — Map Rotations", jours=1)

    synthese = await db.rss_derniere_synthese(max_age_seconds=100 * _JOUR)

    assert "INTRO" in synthese["title"]


@pytest.mark.asyncio
async def test_un_flux_sans_sections_rend_quand_meme_son_dernier_article(tmp_path):
    """Un guid sans « # » n'est pas un patch découpé — on ne rend pas None.

    Tous les flux `knowledge` ne viennent pas de Steam. Grouper par gid ne doit
    pas faire disparaître la synthèse là où il n'y a rien à grouper.
    """
    db = await _base(tmp_path)
    await _section(db, "https://exemple/vieux", "Vieil article", jours=30)
    await _section(db, "https://exemple/neuf", "Article du jour", jours=1)

    synthese = await db.rss_derniere_synthese(max_age_seconds=100 * _JOUR)

    assert synthese is not None
    assert synthese["title"] == "Article du jour"
