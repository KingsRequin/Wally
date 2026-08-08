# tests/test_steam_news.py
"""Les patch notes Apex, lus chez Respawn plutôt que chez un journaliste.

Steam expose ce que les devs publient, en JSON. Deux difficultés : le contenu
arrive en BBCode, et un patch note de saison fait 39 000 caractères — cinq fois
ce qu'on peut injecter dans un prompt. D'où le découpage par SECTIONS : une
question sur World's Edge doit rendre le passage sur World's Edge, pas le
huitième arbitraire du document qui le contient.

La fixture est une réponse réelle capturée le 2026-08-08.
"""
import json
import pathlib

import pytest

from bot.core.steam_news import sections_from_item, strip_bbcode

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "steam" / "apex_news.json"


def _items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["appnews"]["newsitems"]


def _patch_note():
    return max(_items(), key=lambda i: len(i.get("contents", "")))


# ── le nettoyage ─────────────────────────────────────────────────────────────


def test_le_bbcode_disparait():
    assert strip_bbcode("[p]Salut [b]toi[/b][/p]") == "Salut toi"


def test_les_images_et_liens_ne_laissent_pas_de_gribouillis():
    sale = '[p][img src="{STEAM_CLAN_IMAGE}/x.png"][/img][url=https://ea.com]EA[/url][/p]'
    propre = strip_bbcode(sale)
    assert "STEAM_CLAN_IMAGE" not in propre
    assert "img" not in propre
    assert "EA" in propre


def test_un_texte_deja_propre_est_rendu_tel_quel():
    assert strip_bbcode("Rien à nettoyer ici.") == "Rien à nettoyer ici."


# ── le découpage ─────────────────────────────────────────────────────────────


def test_un_patch_note_est_decoupe_en_sections():
    sections = sections_from_item(_patch_note())
    assert len(sections) > 5, "un patch note de saison a bien plus de cinq sections"


def test_chaque_section_porte_son_titre_et_celui_du_patch():
    """« World's Edge » seul ne dit pas de quelle mise à jour on parle."""
    sections = sections_from_item(_patch_note())
    titres = [s["title"] for s in sections]
    assert any("World" in t for t in titres)
    assert all("Patch Notes" in t for t in titres)


def test_aucune_section_n_est_trop_grosse_pour_un_prompt():
    for section in sections_from_item(_patch_note()):
        assert len(section["text"]) <= 1600


def test_chaque_section_a_son_propre_identifiant():
    sections = sections_from_item(_patch_note())
    guids = [s["guid"] for s in sections]
    assert len(guids) == len(set(guids)), "deux sections partagent un identifiant"
    assert all(str(_patch_note()["gid"]) in g for g in guids)


def test_les_sections_gardent_le_contenu_utile():
    texte = " ".join(s["text"] for s in sections_from_item(_patch_note()))
    assert "matchmaking" in texte.lower()
    assert "[/b]" not in texte and "[p]" not in texte


def test_un_article_court_reste_d_un_seul_tenant():
    """Un correctif de trois lignes n'a pas à être éclaté."""
    court = min(_items(), key=lambda i: len(i.get("contents", "")))
    assert len(sections_from_item(court)) == 1


def test_un_article_vide_ne_produit_rien():
    assert sections_from_item({"gid": "1", "title": "vide", "contents": ""}) == []


def test_la_source_est_conservee():
    """Wally doit pouvoir dire s'il cite Respawn ou un communiqué marketing."""
    section = sections_from_item(_patch_note())[0]
    assert section["author"]
    assert section["link"].startswith("http")


# ── le recall doit classer par pertinence ───────────────────────────────────


@pytest.mark.asyncio
async def test_le_recall_classe_par_pertinence_avant_la_recence(tmp_path):
    """Un patch note découpé en 175 sections partage UNE seule date.

    Trier par récence ne départage alors plus rien, et une annonce
    promotionnelle publiée le même jour passe devant la section technique
    qu'on cherchait."""
    import time

    from bot.db.database import Database
    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "t.db")
    db = await Database.create(chemin)
    try:
        await create_v2_tables(chemin)
        maintenant = time.time()
        # La pub est PLUS RÉCENTE, mais ne parle du sujet qu'en passant.
        await db.rss_upsert_article(
            feed_name="Apex Patch Notes", role="knowledge", guid="pub",
            title="Gear up with EA Play", link="", lang="en",
            summary="Join EA Play and get ready for the new season on World's Edge and more.",
            published_at=None, published_ts=maintenant,
        )
        await db.rss_upsert_article(
            feed_name="Apex Patch Notes", role="knowledge", guid="section",
            title="Patch Notes — World's Edge", link="", lang="en",
            summary="World's Edge changes: East Village reworked, War Camp updated, "
                    "Sorting Factory adjusted. World's Edge rotation updated.",
            published_at=None, published_ts=maintenant - 3600,
        )

        res = await db.rss_search_knowledge("world's edge", limit=2, max_age_seconds=86400)

        assert res, "aucun résultat"
        assert "Patch Notes" in res[0]["title"], (
            f"la section technique doit primer, or on a « {res[0]['title']} »"
        )
    finally:
        await db.close()
