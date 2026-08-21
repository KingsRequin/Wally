"""Le modèle de mise en scène de l'overlay.

Un layout illisible ne doit JAMAIS donner un overlay vide : ce réglage se
manipule en plein live, et le pire scénario acceptable est « mal placé ».
Tous les tests de fusion tournent autour de ça.
"""
import re

import pytest

from bot.core.overlay_layout import (
    ANCRAGES, CHAMPS_CHOIX, CHAMPS_PROPRES, ELEMENTS, HORS_FILE, SLUGS_RESERVES,
    ROTATEUR_DUREE_DEFAUT, ROTATEUR_DUREE_MAX, ROTATEUR_DUREE_MIN,
    ROTATEUR_PAUSE_DEFAUT, ROTATEUR_PAUSE_MAX, ROTATEUR_PAUSE_MIN,
    fusionner, layout_par_defaut, scene_par_slug, slug_depuis_nom,
    widgets_qui_passent,
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


def test_seul_le_rotateur_porte_une_pause():
    """La `pause` reste ce qu'elle a toujours été : le temps mort entre deux
    memes du rotateur. Aucun autre élément n'a de boucle où l'insérer.

    (La `duree`, elle, n'est plus l'apanage du rotateur depuis la conception du
    2026-08-21 : elle vaut aussi pour les widgets qui passent, avec un autre
    sens et d'autres bornes — d'où la table indexée par élément.)"""
    for cle, el in ELEMENTS.items():
        assert ("pause" in el) == (cle == "rotator"), (
            f"`pause` n'a rien à faire sur `{cle}`"
        )


def test_les_quatre_elements_hors_file_sont_ceux_qui_ont_leur_propre_rendu():
    """`avatar`, `bubble`, `rotator` et `image` ne passent pas par
    `showWidget` : ils ne reçoivent ni `delai` ni les animations de carte.
    La liste est écrite ici pour qu'un cinquième chemin de rendu casse un test
    au lieu de passer inaperçu."""
    assert HORS_FILE == {"avatar", "bubble", "rotator", "image"}
    assert len(widgets_qui_passent()) == len(ELEMENTS) - 4
    assert not (widgets_qui_passent() & HORS_FILE)


def test_chaque_widget_qui_passe_porte_les_champs_de_rythme():
    """Calculé, pas listé : un widget ajouté à `ELEMENTS` sans son entrée dans
    une table écrite à la main resterait hors de portée du panneau à jamais."""
    for cle in widgets_qui_passent():
        el = ELEMENTS[cle]
        for champ in ("duree", "delai", "anim_duree"):
            assert champ in el, f"{cle} sans {champ}"


def test_un_element_hors_file_na_ni_delai_ni_animation_de_carte():
    """« Délai avant apparition » sur un avatar qui vit en permanence est un
    réglage qu'aucun code ne lit."""
    for cle in HORS_FILE:
        assert "delai" not in ELEMENTS[cle], cle
        assert "anim_insistance" not in ELEMENTS[cle], cle


def test_chaque_champ_propre_a_ses_bornes_ou_ses_choix_declares():
    """Une valeur sans bornes serait rangée telle quelle. Les défauts et les
    tables de validation ont un seul écrivain, ils ne peuvent plus diverger —
    ce test le vérifie plutôt que de l'espérer."""
    for cle, el in ELEMENTS.items():
        bornes = set(CHAMPS_PROPRES.get(cle, {}))
        choix = set(CHAMPS_CHOIX.get(cle, {}))
        assert not (bornes & choix), f"{cle} : champ à la fois borné et à choix"
        for champ in bornes | choix:
            assert champ in el, f"{cle} : `{champ}` validé mais sans défaut"


def test_les_quatre_champs_universels_sont_sur_les_trente_sept():
    """Ils passent tous par `placer()`, le point d'écriture unique du style :
    il n'y a pas de raison qu'un élément en soit privé."""
    for cle, el in ELEMENTS.items():
        assert el["opacite"] == 1.0, cle
        assert el["rotation"] == 0.0, cle
        assert el["miroir"] is False, cle
        assert el["largeur_max"] == 0.0, cle


def test_une_cadence_posee_sur_un_autre_element_est_ignoree():
    """La fusion ne recopie pas ce que le JSON contient : elle remplit ce que
    l'élément DÉCLARE. Sinon un layout écrit à la main ferait apparaître le
    champ sur n'importe quoi, et le panneau finirait par l'afficher.

    `duree` n'est plus l'exemple : depuis la conception du 2026-08-21, elle vaut
    aussi pour les widgets qui passent. `pause` reste l'apanage du rotateur —
    seul à avoir une boucle où insérer un temps mort."""
    assert "pause" not in _scene_avec({"meme": {"pause": 1.0}})["meme"]
    assert "delai" not in _scene_avec({"avatar": {"delai": 3.0}})["avatar"]


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


# ── Les dix réglages par widget (conception du 2026-08-21) ──────────────────

def test_une_duree_a_zero_est_gardee_telle_quelle():
    """0 vaut AUTO : le serveur décide. Sans l'exception, `_borner` la
    remonterait au plancher de 2 s et la valeur LIVRÉE deviendrait une durée de
    deux secondes appliquée à tous les widgets, sur les trois scènes."""
    assert _scene_avec({"poll": {"duree": 0}})["poll"]["duree"] == 0.0


def test_une_duree_hors_bornes_revient_dans_ses_bornes():
    assert _scene_avec({"poll": {"duree": 9000}})["poll"]["duree"] == 180.0
    assert _scene_avec({"poll": {"duree": 0.4}})["poll"]["duree"] == 2.0


def test_la_duree_du_rotateur_garde_ses_propres_bornes():
    """Même mot, autre grandeur : 120 s pour un média, 180 s pour un passage.
    Une table de bornes plate aurait fait dépendre la borne appliquée de
    l'ordre d'écriture."""
    assert _scene_avec({"rotator": {"duree": 150}})["rotator"]["duree"] == 120.0
    assert _scene_avec({"poll": {"duree": 150}})["poll"]["duree"] == 150.0


def test_le_rotateur_na_pas_dauto_sur_sa_duree():
    """Un rotateur à zéro seconde par média n'affiche rien, et il n'y a
    personne derrière pour « décider » à sa place : zéro y est ramené au
    PLANCHER, comme n'importe quelle valeur hors bornes — exactement ce que
    faisait `_borner` avant qu'un « auto » existe ailleurs."""
    assert _scene_avec({"rotator": {"duree": 0}})["rotator"]["duree"] == \
        ROTATEUR_DUREE_MIN


def test_une_animation_inconnue_reprend_le_defaut():
    assert _scene_avec({"poll": {"anim_entree": "nawak"}})["poll"]["anim_entree"] \
        == "glitch"


def test_une_sortie_proposee_en_entree_est_refusee():
    """`fadeOut` en entrée ferait disparaître la carte au moment où elle
    apparaît. Les deux menus sont disjoints, la validation aussi."""
    assert _scene_avec({"poll": {"anim_entree": "fadeOut"}})["poll"]["anim_entree"] \
        == "glitch"
    assert _scene_avec({"poll": {"anim_sortie": "fadeIn"}})["poll"]["anim_sortie"] \
        == "glitch"


def test_un_champ_de_rythme_sur_un_element_qui_ne_le_porte_pas_est_ignore():
    """`avatar` n'a pas de durée d'affichage : il vit en permanence. Une clé
    envoyée par un JSON écrit à la main ne doit pas s'installer dans le modèle,
    sinon le panneau finirait par l'afficher."""
    assert "duree" not in _scene_avec({"avatar": {"duree": 30}})["avatar"]
    assert "delai" not in _scene_avec({"image": {"delai": 3}})["image"]


def test_les_quatre_universels_se_bornent_comme_les_autres():
    el = _scene_avec({"meme": {"opacite": 5, "rotation": -900,
                               "miroir": "oui", "largeur_max": 99999}})["meme"]
    assert el["opacite"] == 1.0
    assert el["rotation"] == -45.0
    assert el["miroir"] is True
    assert el["largeur_max"] == 1920.0


def test_une_largeur_max_a_zero_reste_a_zero():
    """Zéro rend la main au CSS (`max-width: 92vw`). Bornée au plancher, elle
    écraserait chaque carte à 120 px de large."""
    assert _scene_avec({"meme": {"largeur_max": 0}})["meme"]["largeur_max"] == 0.0


def test_un_nouveau_champ_present_a_null_reprend_son_defaut():
    """`.get(clé, défaut)` ne couvre PAS `clé: null` : la clé est présente, sa
    valeur `None` est rendue telle quelle. Piège déjà payé sur ce modèle."""
    el = _scene_avec({"poll": {"duree": None, "anim_entree": None,
                               "miroir": None, "opacite": None,
                               "largeur_max": None}})["poll"]
    assert el["duree"] == 0.0
    assert el["anim_entree"] == "glitch"
    assert el["miroir"] is False
    assert el["opacite"] == 1.0
    assert el["largeur_max"] == 0.0


@pytest.mark.parametrize("brut", [
    {"duree": True},                     # `bool` est un `int` en Python
    {"duree": float("nan")},             # json.loads l'accepte
    {"duree": "12"},                     # une chaîne n'est pas un nombre
    {"anim_entree": 42},                 # un choix n'est pas un entier
    {"anim_entree": ["fadeIn"]},         # ni une liste
])
def test_un_reglage_illisible_reprend_le_defaut(brut):
    el = _scene_avec({"poll": brut})["poll"]
    assert el["duree"] == 0.0
    assert el["anim_entree"] == "glitch"


def test_le_defaut_livre_ne_change_rien_a_ce_qui_est_rendu():
    """LE test qui protège le live : une disposition livrée doit sortir de la
    fusion avec des valeurs qui reproduisent le comportement d'avant ce
    chantier — auto partout, glitch partout, rien d'incliné ni de pâli."""
    for scene in layout_par_defaut()["scenes"]:
        for cle, el in scene["elements"].items():
            assert el["opacite"] == 1.0, cle
            assert el["rotation"] == 0.0, cle
            assert el["miroir"] is False, cle
            assert el["largeur_max"] == 0.0, cle
            if cle != "rotator" and "duree" in el:
                assert el["duree"] == 0.0, cle
            if "anim_entree" in el:
                assert el["anim_entree"] == "glitch", cle
                assert el["anim_sortie"] == "glitch", cle
                assert el["anim_duree"] == 0.15, cle
            if "anim_insistance" in el:
                assert el["anim_insistance"] == "aucune", cle
    # Le rotateur, lui, garde la cadence qu'il avait déjà.
    rot = layout_par_defaut()["scenes"][0]["elements"]["rotator"]
    assert rot["duree"] == ROTATEUR_DUREE_DEFAUT
    assert rot["pause"] == ROTATEUR_PAUSE_DEFAUT
