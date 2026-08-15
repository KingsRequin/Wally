"""Une URL par scène, et l'ancienne qui survit.

`/overlay` reste servie : c'est la source OBS déjà en place chez le streamer,
et la casser pendant la transition mettrait un écran noir en plein live.
"""
import pytest

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


# ── Sécurité ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("charge", [
    'x" onload="alert(1)',
    'x"><script>alert(1)</script>',
    "x' onmouseover='alert(1)",
    'x"><img src=x onerror=alert(1)>',
])
def test_un_slug_hostile_ne_sort_jamais_dans_la_page(overlay_client, charge):
    """Ce slug vient de l'URL et finit dans un attribut HTML.

    Écrit tel quel, `/overlay-x" onload="…` refermait l'attribut et exécutait du
    JavaScript sur le domaine public — celui qui sert aussi le panneau
    d'administration, donc son jeton. Vérifié exploitable en production le
    2026-08-15 : la réponse contenait littéralement
    `data-scene-slug="x" onload="alert(1)"`.

    On vérifie le RÉSULTAT servi, pas la façon de l'obtenir : la page ne doit
    contenir ni la charge telle quelle, ni un attribut refermé.
    """
    r = overlay_client.get(f"/overlay-{charge}")

    assert r.status_code == 200          # jamais d'écran noir, même ici
    assert charge not in r.text
    assert "onload=" not in r.text
    assert "onerror=" not in r.text
    assert "<script>alert" not in r.text
    # Une charge contenant une barre oblique (`</script>`) fait plusieurs
    # segments d'URL : elle n'atteint jamais cette route et retombe sur la page
    # unique, qui est un fichier statique — rien n'y est réfléchi. Quand c'est
    # bien l'overlay qui répond, l'attribut doit être vide et proprement fermé,
    # la page retombant sur la scène par défaut.
    if "data-scene-slug" in r.text:
        assert 'data-scene-slug=""' in r.text


def test_un_slug_legitime_passe_toujours(overlay_client):
    """Le garde-fou ne doit pas manger les slugs valables."""
    for slug in ("start", "jeu", "end", "fin-de-stream", "scene-2"):
        r = overlay_client.get(f"/overlay-{slug}")
        assert r.status_code == 200
        assert f'data-scene-slug="{slug}"' in r.text
