"""Le modèle de mise en scène de l'overlay.

Un layout illisible ne doit JAMAIS donner un overlay vide : ce réglage se
manipule en plein live, et le pire scénario acceptable est « mal placé ».
Tous les tests de fusion tournent autour de ça.
"""
import re

import pytest

from bot.core.overlay_layout import (
    ANCRAGES, CHAMPS_PROPRES, ELEMENTS, SLUGS_RESERVES,
    ROTATEUR_DUREE_DEFAUT, ROTATEUR_DUREE_MAX, ROTATEUR_DUREE_MIN,
    ROTATEUR_PAUSE_DEFAUT, ROTATEUR_PAUSE_MAX, ROTATEUR_PAUSE_MIN,
    fusionner, layout_par_defaut, scene_par_slug, slug_depuis_nom,
)


def _scene_avec(elements: dict) -> dict:
    return fusionner({"defaut": "jeu", "scenes": [
        {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": elements},
    ]})["scenes"][0]["elements"]

# La même regex que la route `/overlay-{slug}` (`bot/dashboard/app.py`) : un
# slug produit ici doit systématiquement la passer, sans quoi la scène devient
# inaccessible en silence dès sa création.
_SLUG_ROUTE_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def test_defaut_porte_les_trois_scenes():
    layout = layout_par_defaut()
    # Le slug DÉRIVE du nom, il n'est pas écrit à côté : une paire posée à la
    # main avait donné « Stream Starting » → `start`, indevinable quand on
    # cherche l'URL à taper dans OBS.
    assert [s["slug"] for s in layout["scenes"]] == [
        "stream-starting", "en-jeu", "fin"]
    assert [s["nom"] for s in layout["scenes"]] == [
        "Stream Starting", "En jeu", "Fin"]
    assert layout["defaut"] == "en-jeu"


def test_le_slug_de_chaque_scene_livree_derive_bien_de_son_nom():
    """Le lien entre les deux ne doit pas pouvoir se défaire en silence : c'est
    ce qui rend l'URL prévisible depuis le nom affiché dans le panneau."""
    for scene in layout_par_defaut()["scenes"]:
        assert scene["slug"] == slug_depuis_nom(scene["nom"])


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


def test_slug_depuis_nom_est_borne_pour_la_route():
    """Un nom un peu long ne doit pas produire un slug que la route
    `/overlay-{slug}` refuse — sinon la scène est inaccessible en silence :
    la page répond 200 avec `data-scene-slug=""` et sert la scène par défaut.
    """
    nom = ("Écran de fin de stream avec le planning de la semaine et les "
           "remerciements")
    slug = slug_depuis_nom(nom)
    assert _SLUG_ROUTE_RE.match(slug)
    assert not slug.endswith("-")   # pas de trait d'union orphelin en coupant


def test_scene_par_slug():
    layout = layout_par_defaut()
    assert scene_par_slug(layout, "stream-starting")["nom"] == "Stream Starting"
    assert scene_par_slug(layout, "inexistante") is None


@pytest.mark.parametrize("brut", [
    # `anchor` en `dict` : `anchor if anchor in ANCRAGES` teste l'appartenance
    # d'un type non hashable.
    {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"meme": {"anchor": {}}}}]},
    # Un élément d'`ordre` en `dict` : `c in ELEMENTS`, même piège.
    {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "ordre": [{}], "elements": {}}]},
    # `defaut` en `dict` : `defaut not in vus` (un `set`), même piège.
    {"defaut": {}, "scenes": [{"slug": "jeu", "elements": {}}]},
])
def test_une_valeur_non_hashable_ne_fait_pas_lever_fusionner(brut):
    """`anchor`, un élément d'`ordre` ou `defaut` peuvent arriver en `dict`/
    `list` depuis un JSON par ailleurs parfaitement légal. `in` sur un type
    non hashable lève un `TypeError` — sur le chemin qui sert la page en
    plein live. Une exception non rattrapée est pire qu'un layout mal formé :
    ce module doit rendre quelque chose d'affichable, jamais planter."""
    layout = fusionner(brut)
    scene = layout["scenes"][0]
    assert layout["defaut"] == "jeu"
    assert set(scene["elements"]) == set(ELEMENTS)
    for el in scene["elements"].values():
        assert el["anchor"] in ANCRAGES
    assert set(scene["ordre"]) == set(ELEMENTS)


def test_un_booleen_present_a_null_reprend_son_defaut():
    """`.get(clé, défaut)` ne protège pas une clé PRÉSENTE valant `null` : le
    piège que le commentaire de `_fusionner_element` nomme déjà pour les
    champs numériques, mais qui touchait encore `hidden`/`locked`/`solo` —
    `bool(None)` vaut `False`, quel que soit le défaut de l'élément."""
    brut = {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"meme": {"solo": None}}},
    ]}
    meme = fusionner(brut)["scenes"][0]["elements"]["meme"]
    assert meme["solo"] == ELEMENTS["meme"]["solo"]  # True : reste au défaut


def test_goal_et_uptime_ne_sont_plus_des_elements():
    """`goal` et `uptime` ne sont jamais rendus sous ce nom : `_publish_goal`
    (overlay_narrator.py) publie un `gauge`, et `uptime` est aliasé en
    `counter`. Les lister ici n'aurait aucun effet sur l'affichage."""
    assert "goal" not in ELEMENTS
    assert "uptime" not in ELEMENTS


# ── La cadence du rotateur de memes ─────────────────────────────────────────
#
# Deux réglages d'un SEUL élément. Ils étaient figés dans le code de la page —
# neuf secondes d'affichage, cinq de pause — et se réglaient par l'URL de la
# source OBS, qui n'existe plus.


def test_le_rotateur_part_sur_la_cadence_quil_avait_en_dur():
    """Le rythme du live ne change pas parce qu'on a rendu ces valeurs
    réglables : qui n'y touche pas garde exactement ce qu'il avait."""
    assert ELEMENTS["rotator"]["duree"] == ROTATEUR_DUREE_DEFAUT == 9.0
    assert ELEMENTS["rotator"]["pause"] == ROTATEUR_PAUSE_DEFAUT == 5.0


def test_seul_le_rotateur_porte_la_cadence():
    """Trente-quatre éléments × trois scènes : poser ces deux champs partout
    écrirait deux cents valeurs que rien ne lit, et le panneau proposerait de
    régler la « durée d'affichage » d'un dé."""
    for cle, el in ELEMENTS.items():
        for champ in CHAMPS_PROPRES:
            assert (champ in el) == (cle == "rotator"), (
                f"`{champ}` n'a rien à faire sur `{cle}`"
            )


def test_une_cadence_posee_sur_un_autre_element_est_ignoree():
    """La fusion ne recopie pas ce que le JSON contient : elle remplit ce que
    l'élément DÉCLARE. Sinon un layout écrit à la main ferait apparaître le
    champ sur n'importe quoi, et le panneau finirait par l'afficher."""
    elements = _scene_avec({"meme": {"duree": 3.0, "pause": 1.0}})
    assert "duree" not in elements["meme"]
    assert "pause" not in elements["meme"]


def test_la_cadence_reglee_est_gardee():
    rotator = _scene_avec({"rotator": {"duree": 3.5, "pause": 1.5}})["rotator"]
    assert rotator["duree"] == 3.5
    assert rotator["pause"] == 1.5


def test_une_pause_a_zero_est_gardee():
    """`0` est un réglage VOULU : il enchaîne les memes sans temps mort. Le
    ramener au défaut de cinq secondes serait le bug le plus discret possible —
    la valeur revient toute seule sans que rien ne le dise."""
    assert _scene_avec({"rotator": {"pause": 0}})["rotator"]["pause"] == 0.0


def test_la_cadence_hors_bornes_est_ramenee():
    """Une durée de deux dixièmes ne laisse voir que le glitch de transition ;
    une pause d'une heure fige la zone, et le gardien anti-gel de la boucle
    attendrait `3 × (durée + pause) + 10 s` avant de la relancer."""
    rotator = _scene_avec({"rotator": {"duree": 0.2, "pause": 3600}})["rotator"]
    assert rotator["duree"] == ROTATEUR_DUREE_MIN
    assert rotator["pause"] == ROTATEUR_PAUSE_MAX
    haut = _scene_avec({"rotator": {"duree": 9999, "pause": -5}})["rotator"]
    assert haut["duree"] == ROTATEUR_DUREE_MAX
    assert haut["pause"] == ROTATEUR_PAUSE_MIN


@pytest.mark.parametrize("brut", [
    {},                                  # champ absent : layout d'avant
    {"duree": None, "pause": None},      # clé PRÉSENTE à `null`
    {"duree": "trois", "pause": "deux"},
    {"duree": True, "pause": True},      # `bool` est un `int` en Python
    {"duree": float("nan"), "pause": float("nan")},
])
def test_une_cadence_illisible_reprend_le_defaut(brut):
    """`.get(clé, défaut)` ne couvre pas une clé présente valant `null` — le
    piège déjà payé sur `hidden`/`locked`/`solo`. Et une cadence à `0` héritée
    d'un `bool` ou d'un `NaN` figerait la boucle."""
    rotator = _scene_avec({"rotator": brut})["rotator"]
    assert rotator["duree"] == ROTATEUR_DUREE_DEFAUT
    assert rotator["pause"] == ROTATEUR_PAUSE_DEFAUT


def test_les_widgets_evenementiels_ont_une_place():
    """Ces `kind` de `BUILDERS` (overlay.js) sont publiés directement par le
    serveur — jamais par l'outil `show_overlay`, dont l'enum ne les liste pas.
    Absents d'`ELEMENTS`, ils resteraient sans conteneur le jour où `#widgets`
    se scinde par clé, et disparaîtraient de l'overlay sans lever d'erreur."""
    for kind in ("clip", "clip_top", "planning", "prediction", "quote",
                 "raid", "wave"):
        assert kind in ELEMENTS
