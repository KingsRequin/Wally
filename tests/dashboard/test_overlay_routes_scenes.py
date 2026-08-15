"""Une URL par scène, et l'ancienne qui survit.

`/overlay` reste servie : c'est la source OBS déjà en place chez le streamer,
et la casser pendant la transition mettrait un écran noir en plein live.
"""
from bot.core.overlay_layout import SLUGS_RESERVES


def test_overlay_sans_slug_repond_toujours(overlay_client):
    assert overlay_client.get("/overlay").status_code == 200


def test_chaque_scene_a_son_url(overlay_client):
    for slug in ("start", "jeu", "end"):
        r = overlay_client.get(f"/overlay-{slug}")
        assert r.status_code == 200
        assert "overlay_layout.js" in r.text


def test_la_page_porte_son_slug(overlay_client):
    assert 'data-scene-slug="jeu"' in overlay_client.get("/overlay-jeu").text


def test_les_slugs_reserves_ne_sont_pas_captes(overlay_client):
    """`/overlay-image` et `/overlay-rotation` existaient AVANT les scènes.

    Elles sont déclarées avant la route paramétrée, qui les capterait sinon.
    """
    for reserve in ("image", "rotation"):
        assert reserve in SLUGS_RESERVES
        r = overlay_client.get(f"/overlay-{reserve}")
        assert r.status_code == 200
        # La page de scène porte cet attribut ; les deux anciennes pages, non.
        assert "data-scene-slug" not in r.text


def test_une_scene_inconnue_sert_quand_meme_une_page(overlay_client):
    """OBS peut pointer sur une scène supprimée. Écran noir interdit."""
    assert overlay_client.get("/overlay-fantome").status_code == 200
