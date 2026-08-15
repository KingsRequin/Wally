"""Le modèle de mise en scène de l'overlay.

Un layout illisible ne doit JAMAIS donner un overlay vide : ce réglage se
manipule en plein live, et le pire scénario acceptable est « mal placé ».
Tous les tests de fusion tournent autour de ça.
"""
import pytest

from bot.core.overlay_layout import (
    ANCRAGES, ELEMENTS, SLUGS_RESERVES,
    fusionner, layout_par_defaut, scene_par_slug, slug_depuis_nom,
)


def test_defaut_porte_les_trois_scenes():
    layout = layout_par_defaut()
    assert [s["slug"] for s in layout["scenes"]] == ["start", "jeu", "end"]
    assert layout["defaut"] == "jeu"


def test_defaut_place_chaque_element_de_chaque_scene():
    layout = layout_par_defaut()
    for scene in layout["scenes"]:
        assert set(scene["elements"]) == set(ELEMENTS)
        for cle, el in scene["elements"].items():
            assert el["anchor"] in ANCRAGES
            assert 0.0 <= el["x"] <= 100.0
            assert 0.0 <= el["y"] <= 100.0


def test_fusion_dun_layout_absent_rend_les_defauts():
    assert fusionner(None) == layout_par_defaut()


def test_fusion_dun_json_corrompu_rend_les_defauts():
    # Ni dict, ni scenes : provenance inconnue, on ne devine pas.
    assert fusionner({"n'importe": "quoi"}) == layout_par_defaut()
    assert fusionner([]) == layout_par_defaut()


def test_un_element_absent_reprend_son_defaut():
    """Ajouter un dix-huitième widget dans six mois ne doit pas faire exploser
    la disposition existante."""
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"avatar": {"x": 10.0, "y": 20.0, "anchor": "top-left",
                                 "scale": 1.0, "hidden": False,
                                 "locked": False, "solo": False}}},
    ]}
    scene = fusionner(brut)["scenes"][0]
    assert scene["elements"]["avatar"]["x"] == 10.0        # le réglé est gardé
    assert scene["elements"]["bingo"] == ELEMENTS["bingo"] # l'absent revient


def test_un_element_inconnu_est_ignore():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"licorne": {"x": 5.0, "y": 5.0}}},
    ]}
    assert "licorne" not in fusionner(brut)["scenes"][0]["elements"]


def test_les_valeurs_hors_bornes_sont_ramenees():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [],
         "elements": {"avatar": {"x": 999.0, "y": -50.0, "scale": 12.0,
                                 "anchor": "nulle-part", "hidden": "oui",
                                 "locked": False, "solo": False}}},
    ]}
    avatar = fusionner(brut)["scenes"][0]["elements"]["avatar"]
    assert avatar["x"] == 100.0
    assert avatar["y"] == 0.0
    assert avatar["scale"] == 2.0
    assert avatar["anchor"] == ELEMENTS["avatar"]["anchor"]   # ancrage inconnu
    assert avatar["hidden"] is True                           # coercition franche


def test_ordre_complete_les_elements_manquants():
    """`ordre` pilote l'empilement : un élément absent de la liste serait
    invisible au rendu, pas seulement mal empilé."""
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": ["avatar"], "elements": {}},
    ]}
    ordre = fusionner(brut)["scenes"][0]["ordre"]
    assert ordre[0] == "avatar"
    assert set(ordre) == set(ELEMENTS)


def test_une_scene_sans_slug_est_jetee_pas_tout_le_layout():
    brut = {"version": 1, "defaut": "jeu", "scenes": [
        {"nom": "sans slug", "elements": {}},
        {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": {}},
    ]}
    assert [s["slug"] for s in fusionner(brut)["scenes"]] == ["jeu"]


def test_un_layout_sans_aucune_scene_valable_rend_les_defauts():
    brut = {"version": 1, "defaut": "jeu", "scenes": [{"nom": "sans slug"}]}
    assert fusionner(brut) == layout_par_defaut()


def test_defaut_pointant_une_scene_absente_retombe_sur_la_premiere():
    brut = {"version": 1, "defaut": "fantome", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": {}},
    ]}
    assert fusionner(brut)["defaut"] == "jeu"


@pytest.mark.parametrize("nom,attendu", [
    ("Stream Starting", "stream-starting"),
    ("Fin de stream", "fin-de-stream"),
    ("  Écran   d'attente  ", "ecran-d-attente"),
    ("!!!", "scene"),
    ("image", "image-2"),          # slug réservé : suffixé, pas refusé
])
def test_slug_depuis_nom(nom, attendu):
    assert slug_depuis_nom(nom) == attendu


def test_slug_depuis_nom_evite_les_reserves():
    for reserve in SLUGS_RESERVES:
        assert slug_depuis_nom(reserve) not in SLUGS_RESERVES


def test_scene_par_slug():
    layout = layout_par_defaut()
    assert scene_par_slug(layout, "start")["nom"] == "Stream Starting"
    assert scene_par_slug(layout, "inexistante") is None
