"""Les groupes d'éléments de la mise en scène, côté modèle.

Un groupe n'est qu'un nom et une liste de clés — c'est justement pour ça qu'il
se casse en silence : une clé qui n'existe plus, un élément réclamé par deux
groupes, un nom vide, et le panneau affiche un en-tête qui ne recouvre rien ou
déplace deux fois le même widget. Tout ce qui suit vérifie que le modèle range
au lieu de jeter, et qu'il ne peut pas rendre un état incohérent.

Ces tests échouent tous sur le code d'avant : `_fusionner_groupes`,
`_ordre_avec_groupes`, `GROUPES_DEFAUT` et la clé `groupes` d'une scène
n'existaient pas.
"""
import json

import pytest

from bot.core.overlay_layout import (
    ELEMENTS,
    GROUPE_NOM_DEFAUT,
    GROUPES_DEFAUT,
    fusionner,
    groupes_par_defaut,
    layout_par_defaut,
)


def _scene(**extra) -> dict:
    base = {"slug": "jeu", "nom": "En jeu", "ordre": [], "elements": {}}
    base.update(extra)
    return {"scenes": [base]}


def _groupes(brut) -> list[dict]:
    return fusionner(_scene(groupes=brut))["scenes"][0]["groupes"]


# ── Ce que le modèle livre ──────────────────────────────────────────────────

def test_les_groupes_livres_ne_nomment_que_des_elements_qui_existent():
    """Un membre inventé serait un en-tête qui recouvre du vide."""
    for groupe in GROUPES_DEFAUT:
        for cle in groupe["membres"]:
            assert cle in ELEMENTS, f"{groupe['id']} → {cle} inconnu"


def test_aucun_element_n_est_livre_dans_deux_groupes():
    """L'exclusivité commence par les défauts : la livrer cassée ferait naître
    l'incohérence au premier chargement."""
    vus: set[str] = set()
    for groupe in GROUPES_DEFAUT:
        for cle in groupe["membres"]:
            assert cle not in vus, f"{cle} réclamé deux fois"
            vus.add(cle)


def test_chaque_scene_livree_a_ses_PROPRES_groupes():
    """Une liste partagée ferait bouger les trois scènes au premier renommage —
    exactement ce que la copie des éléments évite déjà."""
    layout = layout_par_defaut()
    a, b = layout["scenes"][0], layout["scenes"][1]
    a["groupes"][0]["nom"] = "Renommé ici seulement"
    a["groupes"][0]["membres"].append("counter")
    assert b["groupes"][0]["nom"] != "Renommé ici seulement"
    assert "counter" not in b["groupes"][0]["membres"]
    # Et la table de référence n'a pas bougé non plus.
    assert GROUPES_DEFAUT[0]["nom"] != "Renommé ici seulement"


def test_les_membres_livres_se_suivent_dans_l_empilement():
    """`_ordre_avec_groupes` appliqué aux défauts : ce qui est livré est déjà
    cohérent, sinon la liste mentirait dès la première ouverture."""
    ordre = layout_par_defaut()["scenes"][0]["ordre"]
    for groupe in GROUPES_DEFAUT:
        rangs = sorted(ordre.index(c) for c in groupe["membres"])
        assert rangs == list(range(rangs[0], rangs[0] + len(rangs))), groupe["id"]


# ── La fusion ───────────────────────────────────────────────────────────────

def test_la_cle_absente_reprend_les_groupes_livres():
    """Toute disposition rangée avant ce chantier n'a pas la clé."""
    assert _groupes(None) == groupes_par_defaut()
    assert fusionner({"scenes": [{"slug": "jeu", "ordre": [], "elements": {}}]}
                     )["scenes"][0]["groupes"] == groupes_par_defaut()


def test_une_liste_VIDE_est_respectee():
    """Dissoudre tous ses groupes est une décision. Les voir repousser au
    rechargement rendrait la dissolution impossible — c'est la différence entre
    « absent » et « vidé », et `.get(clé, défaut)` ne la fait pas."""
    assert _groupes([]) == []


def test_un_groupe_qui_nomme_un_element_inconnu_garde_les_autres():
    """Un widget retiré du code ne doit pas emporter le groupe entier."""
    groupes = _groupes([{"id": "g1", "nom": "Mixte",
                         "membres": ["dice", "widget_disparu", "wheel"]}])
    assert len(groupes) == 1
    assert groupes[0]["membres"] == ["dice", "wheel"]


def test_un_groupe_dont_TOUS_les_membres_sont_inconnus_part_sans_bruit():
    """Il n'y a plus rien à manipuler dessous — mais les voisins restent."""
    groupes = _groupes([
        {"id": "mort", "nom": "Fantômes", "membres": ["ancien", "disparu"]},
        {"id": "vivant", "nom": "Dés", "membres": ["dice"]},
    ])
    assert [g["id"] for g in groupes] == ["vivant"]


def test_un_element_reclame_par_deux_groupes_reste_dans_le_PREMIER():
    """L'exclusivité tenue au point d'écriture, pas seulement dans le panneau.

    Sans elle, déplacer le premier groupe déplacerait un membre du second, dont
    le cadre englobant mentirait aussitôt.
    """
    groupes = _groupes([
        {"id": "a", "nom": "A", "membres": ["dice", "wheel"]},
        {"id": "b", "nom": "B", "membres": ["wheel", "coinflip"]},
    ])
    assert groupes[0]["membres"] == ["dice", "wheel"]
    assert groupes[1]["membres"] == ["coinflip"]


def test_le_second_groupe_vide_par_l_exclusivite_disparait():
    groupes = _groupes([
        {"id": "a", "nom": "A", "membres": ["dice"]},
        {"id": "b", "nom": "B", "membres": ["dice"]},
    ])
    assert [g["id"] for g in groupes] == ["a"]


def test_un_membre_repete_dans_le_meme_groupe_ne_compte_qu_une_fois():
    groupes = _groupes([{"id": "a", "nom": "A", "membres": ["dice", "dice"]}])
    assert groupes[0]["membres"] == ["dice"]


def test_un_groupe_sans_nom_garde_ses_membres_et_prend_un_nom_de_repli():
    """C'est l'appartenance qui coûte à composer, pas le mot. Même parti pris
    que `nom` sur une scène, qui retombe sur son slug."""
    for nom in (None, "", "   ", 42, {"nom": "non"}):
        groupes = _groupes([{"id": "a", "nom": nom, "membres": ["dice"]}])
        assert groupes[0]["nom"] == GROUPE_NOM_DEFAUT, nom
        assert groupes[0]["membres"] == ["dice"]


def test_un_nom_est_debarrasse_de_ses_espaces():
    assert _groupes([{"id": "a", "nom": "  Jeux  ",
                      "membres": ["dice"]}])[0]["nom"] == "Jeux"


def test_un_groupe_sans_id_exploitable_est_jete():
    """Sans identité on ne peut ni le renommer ni le dissoudre : il resterait à
    l'écran sans prise. Le voisin, lui, survit."""
    groupes = _groupes([
        {"nom": "Sans id", "membres": ["dice"]},
        {"id": "   ", "nom": "Vide", "membres": ["wheel"]},
        {"id": 7, "nom": "Nombre", "membres": ["coinflip"]},
        {"id": "ok", "nom": "Bon", "membres": ["rps"]},
    ])
    assert [g["id"] for g in groupes] == ["ok"]
    assert groupes[0]["membres"] == ["rps"]


def test_un_id_en_double_ne_garde_que_le_premier():
    groupes = _groupes([
        {"id": "a", "nom": "Premier", "membres": ["dice"]},
        {"id": "a", "nom": "Second", "membres": ["wheel"]},
    ])
    assert [(g["id"], g["nom"]) for g in groupes] == [("a", "Premier")]


@pytest.mark.parametrize("brut", [
    "des groupes", 42, {"a": ["dice"]},
])
def test_une_valeur_aberrante_a_la_place_de_la_liste_reprend_les_defauts(brut):
    assert _groupes(brut) == groupes_par_defaut()


def test_un_groupe_qui_n_est_pas_un_dictionnaire_ne_fait_pas_tomber_la_scene():
    """Le JSON est éditable à la main, et il est lu en plein live."""
    layout = fusionner(_scene(groupes=["texte", None, 3,
                                       {"id": "a", "nom": "A",
                                        "membres": ["dice"]}]))
    assert [g["id"] for g in layout["scenes"][0]["groupes"]] == ["a"]
    assert len(layout["scenes"][0]["elements"]) == len(ELEMENTS)


def test_des_membres_d_un_type_impossible_ne_levent_pas():
    """`in ELEMENTS` sur un `dict` lèverait `unhashable type`."""
    groupes = _groupes([{"id": "a", "nom": "A",
                         "membres": [{"cle": "dice"}, ["wheel"], None, "rps"]}])
    assert groupes[0]["membres"] == ["rps"]


def test_des_membres_qui_ne_sont_pas_une_liste_jettent_le_groupe():
    assert _groupes([{"id": "a", "nom": "A", "membres": "dice"}]) == []


# ── L'empilement rendu contigu ──────────────────────────────────────────────

def test_les_membres_epars_sont_rapproches_a_la_place_du_PREMIER():
    """L'ordre de la liste EST l'empilement : une liste qui montre trois membres
    l'un sous l'autre pendant que deux widgets s'intercalent dans l'empilement
    réel mentirait sur la seule chose qu'elle raconte."""
    ordre = ["dice", "counter", "wheel", "quote", "coinflip"]
    rendu = fusionner(_scene(
        ordre=ordre, elements={},
        groupes=[{"id": "a", "nom": "A",
                  "membres": ["dice", "wheel", "coinflip"]}],
    ))["scenes"][0]["ordre"]
    assert rendu[:5] == ["dice", "wheel", "coinflip", "counter", "quote"]


def test_un_empilement_deja_contigu_ne_bouge_PAS():
    """Le garde-fou qui compte : ouvrir le panneau ne doit pas rebattre une
    disposition réglée à la main."""
    layout = layout_par_defaut()
    avant = list(layout["scenes"][0]["ordre"])
    assert fusionner(layout)["scenes"][0]["ordre"] == avant


def test_l_ordre_relatif_des_membres_est_conserve():
    rendu = fusionner(_scene(
        ordre=["wheel", "counter", "dice"], elements={},
        groupes=[{"id": "a", "nom": "A", "membres": ["dice", "wheel"]}],
    ))["scenes"][0]["ordre"]
    assert rendu[:3] == ["wheel", "dice", "counter"]


def test_un_membre_absent_de_l_ordre_reste_dans_l_empilement():
    """`ordre` est complété AVANT le regroupement : un membre traité trop tôt
    disparaîtrait de la sortie, donc de l'écran."""
    rendu = fusionner(_scene(
        ordre=["counter"], elements={},
        groupes=[{"id": "a", "nom": "A", "membres": ["dice", "wheel"]}],
    ))["scenes"][0]["ordre"]
    assert set(rendu) == set(ELEMENTS)
    assert abs(rendu.index("dice") - rendu.index("wheel")) == 1


# ── L'aller-retour d'enregistrement ─────────────────────────────────────────

def test_un_layout_range_puis_relu_rend_les_memes_groupes():
    """Le vrai chemin : `fusionner` → JSON → `fusionner`. C'est ce que fait le
    store à chaque publication."""
    depart = fusionner(_scene(
        ordre=list(ELEMENTS), elements={},
        groupes=[{"id": "mien", "nom": "Le mien", "membres": ["dice", "wheel"]}],
    ))
    relu = fusionner(json.loads(json.dumps(depart)))
    assert relu == depart
    assert relu["scenes"][0]["groupes"] == [
        {"id": "mien", "nom": "Le mien", "membres": ["dice", "wheel"]}]


def test_deux_scenes_gardent_chacune_ses_groupes():
    """La justification du choix « par scène », vérifiée : le découpage de l'une
    ne s'impose pas à l'autre."""
    layout = fusionner({"scenes": [
        {"slug": "a", "ordre": [], "elements": {},
         "groupes": [{"id": "g", "nom": "Ici", "membres": ["dice"]}]},
        {"slug": "b", "ordre": [], "elements": {}, "groupes": []},
    ]})
    assert [g["id"] for g in layout["scenes"][0]["groupes"]] == ["g"]
    assert layout["scenes"][1]["groupes"] == []


def test_une_scene_sans_groupe_exploitable_ne_perd_ni_ses_elements_ni_son_ordre():
    scene = fusionner(_scene(groupes=[{"id": "a", "membres": ["inconnu"]}])
                      )["scenes"][0]
    assert scene["groupes"] == []
    assert set(scene["ordre"]) == set(ELEMENTS)
    assert len(scene["elements"]) == len(ELEMENTS)
