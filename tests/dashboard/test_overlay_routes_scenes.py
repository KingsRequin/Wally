"""Une URL par scène, et l'ancienne qui survit.

`/overlay` reste servie : c'est la source OBS déjà en place chez le streamer,
et la casser pendant la transition mettrait un écran noir en plein live.
"""
import re

import pytest

from bot.core.overlay_layout import SLUGS_RESERVES

_SCENE_SLUG_ATTR_RE = re.compile(r'data-scene-slug="([^"]*)"')


def _scene_slug_attr(texte: str) -> str | None:
    """La valeur de l'attribut `data-scene-slug`, ou `None` si la page ne le
    porte pas (`/overlay-image`, `/overlay-rotation`, ou une charge qui n'a
    jamais atteint cette route).

    Cible l'attribut précisément : asserter sur les 61 Ko de la page entière
    ferait casser un test de sécurité le jour où l'overlay gagne un `onload=`
    légitime ailleurs, sans rapport avec le slug.
    """
    m = _SCENE_SLUG_ATTR_RE.search(texte)
    return m.group(1) if m else None


def test_overlay_sans_slug_repond_toujours(overlay_client):
    assert overlay_client.get("/overlay").status_code == 200


def test_chaque_scene_a_son_url(overlay_client):
    for slug in ("stream-starting", "en-jeu", "fin"):
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


def test_lancienne_source_du_rotateur_explique_son_remplacement(overlay_client):
    """La page a perdu sa boucle : les memes s'affichaient en double tant que
    les deux sources tournaient. La ROUTE, elle, est gardée — cette source est
    peut-être encore dans une scène OBS, où un 404 ne montrerait qu'un
    rectangle vide, découvert en plein live.
    """
    r = overlay_client.get("/overlay-rotation")

    assert r.status_code == 200
    corps = r.text[r.text.index("<body"):]
    assert "remplacée" in corps           # lisible À L'ÉCRAN, pas en commentaire
    assert "/overlay-&lt;scène&gt;" in corps
    assert "/api/public/rotation" not in r.text   # plus aucune boucle


def test_une_scene_inconnue_sert_quand_meme_une_page(overlay_client):
    """OBS peut pointer sur une scène supprimée. Écran noir interdit."""
    assert overlay_client.get("/overlay-fantome").status_code == 200


# ── Sécurité ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("charge", [
    'x" onload="alert(1)',
    'x"><svg onload=alert(1)>',
    "x' onmouseover='alert(1)",
    'x"><img src=x onerror=alert(1)>',
    'x＂><svg onload=alert(1)>',   # guillemet Unicode pleine chasse (U+FF02)
])
def test_un_slug_hostile_ne_sort_jamais_dans_la_page(overlay_client, charge):
    """Ce slug vient de l'URL et finit dans un attribut HTML.

    Écrit tel quel, `/overlay-x" onload="…` refermait l'attribut et exécutait du
    JavaScript sur le domaine public — celui qui sert aussi le panneau
    d'administration, donc son jeton. Vérifié exploitable en production le
    2026-08-15 : la réponse contenait littéralement
    `data-scene-slug="x" onload="alert(1)"`.

    Aucune de ces charges ne contient de barre oblique : contrairement à
    `x"><script>alert(1)</script>`, qui fait plusieurs segments d'URL et
    n'atteint jamais cette route (elle retombe sur la page unique, un fichier
    statique où rien n'est réfléchi — un test dessus ne testerait rien), elles
    arrivent bien jusqu'à `overlay_scene()`.

    On vérifie le RÉSULTAT servi, pas la façon de l'obtenir — et on le vérifie
    sur l'ATTRIBUT précisément, pas sur les 61 Ko de la page : un `onload=`
    légitime ajouté un jour ailleurs à l'overlay ne doit pas faire casser ce
    test sans rapport.
    """
    r = overlay_client.get(f"/overlay-{charge}")

    assert r.status_code == 200          # jamais d'écran noir, même ici
    assert charge not in r.text
    # Aucun de ces caractères n'est valide dans un slug : l'attribut retombe
    # vide, proprement fermé, sur la scène par défaut.
    assert _scene_slug_attr(r.text) == ""


def test_un_slug_legitime_passe_toujours(overlay_client):
    """Le garde-fou ne doit pas manger les slugs valables."""
    for slug in ("stream-starting", "en-jeu", "fin", "fin-de-stream", "scene-2"):
        r = overlay_client.get(f"/overlay-{slug}")
        assert r.status_code == 200
        assert f'data-scene-slug="{slug}"' in r.text


def test_une_charge_pourcent_encodee_ne_sort_pas_dans_la_page(overlay_client):
    """La même charge que `test_un_slug_hostile_ne_sort_jamais_dans_la_page`,
    mais tapée en pourcent-encodé dans l'URL — comme un lien copié depuis un
    navigateur ou un champ de config OBS le ferait. Le décodage se fait avant
    la validation, donc le résultat doit être identique : attribut vide.
    """
    r = overlay_client.get("/overlay-x%22%3E%3Csvg%20onload%3Dalert(1)%3E")

    assert r.status_code == 200
    assert _scene_slug_attr(r.text) == ""


def test_un_slug_de_65_caracteres_est_rejete(overlay_client):
    """La route n'accepte que 64 caractères — un de plus doit être refusé,
    pas tronqué en silence."""
    r = overlay_client.get("/overlay-" + "a" * 65)

    assert r.status_code == 200
    assert _scene_slug_attr(r.text) == ""


def test_un_saut_de_ligne_final_ne_passe_pas_la_validation(overlay_client):
    """`$` accepte un saut de ligne final en Python — `abc\\n` passait la
    validation de `_SLUG_SCENE_RE` alors que le docstring de la route affirme
    le format vérifié. Inoffensif dans un attribut entre guillemets, mais le
    format n'était pas ce qu'il prétendait être.
    """
    r = overlay_client.get("/overlay-abc%0A")

    assert r.status_code == 200
    valeur = _scene_slug_attr(r.text)
    assert valeur == ""
    assert "\n" not in (valeur or "")
