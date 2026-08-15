"""« Wally reste visible » : un réglage par élément, séparé de `solo`.

`solo` répondait à DEUX questions à la fois : cet élément chasse-t-il les autres
widgets, et efface-t-il l'avatar pendant son affichage ? Ce sont deux choses
différentes — on peut vouloir un meme qui occupe seul la scène mais garde Wally
à côté pour qu'il le commente. `wally_visible` porte désormais la seconde.

Ce que ces tests protègent avant tout : le DÉFAUT reproduit exactement le
comportement d'avant, pour les 34 éléments. Personne ne doit voir son overlay
changer parce qu'on a ajouté un réglage.
"""
import json
from pathlib import Path

import pytest

from bot.core.overlay_layout import ELEMENTS, fusionner, layout_par_defaut
from bot.core.overlay_layout_store import (
    LAYOUT_KEY, charger_layout, enregistrer_layout,
)

_JS = Path("bot/dashboard/static/overlay.js")
_JS_ADMIN = Path("bot/dashboard/static/overlay_admin.js")


class _State:
    """La base réduite à sa clé-valeur, comme dans `test_overlay_layout_store`."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


# ── Le défaut, élément par élément ──────────────────────────────────────────

def test_le_defaut_reproduit_lancien_comportement_pour_chaque_element():
    """Avant ce réglage, c'était `solo` qui effaçait l'avatar. Le défaut doit
    donc valoir `not solo` — sur les 34 éléments, sans exception : un seul écart
    et le streamer découvre un overlay différent sans avoir rien touché."""
    assert len(ELEMENTS) == 34
    for cle, el in ELEMENTS.items():
        assert el["wally_visible"] is (not el["solo"]), cle


def test_les_elements_qui_cohabitent_gardent_wally():
    """Le sens concret du défaut, écrit une fois : ceux qui s'installent à côté
    (bingo, stats, rotateur…) ne l'effaçaient pas, ceux qui prennent la scène
    (meme, clip, dé…) l'effaçaient."""
    for cle in ("avatar", "bubble", "rotator", "bingo", "stats", "talkers"):
        assert ELEMENTS[cle]["wally_visible"] is True, cle
    for cle in ("meme", "clip", "image", "dice", "wheel", "apex_rank"):
        assert ELEMENTS[cle]["wally_visible"] is False, cle


def test_chaque_scene_livree_porte_le_champ():
    for scene in layout_par_defaut()["scenes"]:
        for cle, el in scene["elements"].items():
            assert isinstance(el["wally_visible"], bool), cle


# ── La fusion ───────────────────────────────────────────────────────────────

def test_le_reglage_survit_a_la_fusion():
    """Le cas qui motive tout le chantier : un meme exclusif, mais Wally reste."""
    brut = {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"meme": {"solo": True, "wally_visible": True}}},
    ]}
    meme = fusionner(brut)["scenes"][0]["elements"]["meme"]
    assert meme["solo"] is True
    assert meme["wally_visible"] is True


def test_un_champ_present_a_null_reprend_son_defaut():
    """`.get(clé, défaut)` ne protège pas une clé PRÉSENTE valant `null` :
    `bool(None)` vaut `False`, quel que soit le défaut de l'élément. Le piège
    déjà corrigé pour `hidden`/`locked`/`solo`, qui vaut aussi pour celui-ci —
    un `bingo` reviendrait à « efface Wally », qu'il n'a jamais fait."""
    brut = {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"bingo": {"wally_visible": None},
                                     "meme": {"wally_visible": None}}},
    ]}
    elements = fusionner(brut)["scenes"][0]["elements"]
    assert elements["bingo"]["wally_visible"] is True    # reste au défaut
    assert elements["meme"]["wally_visible"] is False    # reste au défaut


def test_un_element_absent_du_json_reprend_son_defaut():
    """La fusion ne remplace jamais : un layout rangé AVANT l'ajout du champ ne
    le porte pour aucun élément, et doit se comporter comme avant."""
    brut = {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"meme": {"x": 10.0, "y": 20.0,
                                              "anchor": "top-left", "scale": 1.0,
                                              "hidden": False, "locked": False,
                                              "solo": True}}},
    ]}
    elements = fusionner(brut)["scenes"][0]["elements"]
    assert elements["meme"]["x"] == 10.0                       # le réglé est gardé
    assert elements["meme"]["wally_visible"] is False          # défaut repris
    assert elements["bingo"] == ELEMENTS["bingo"]              # l'absent entier


def test_une_valeur_aberrante_est_ramenee_a_un_booleen():
    """Un JSON écrit à la main peut porter « oui » ou 1."""
    brut = {"defaut": "jeu", "scenes": [
        {"slug": "jeu", "elements": {"meme": {"wally_visible": "oui"}}},
    ]}
    assert fusionner(brut)["scenes"][0]["elements"]["meme"]["wally_visible"] is True


# ── L'aller-retour d'enregistrement ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_reglage_survit_a_un_aller_retour_denregistrement():
    """Enregistré puis relu depuis la base : le champ doit revenir tel quel.
    Sans lui dans `_fusionner_element`, l'enregistrement l'aurait effacé en
    silence — le panneau aurait montré une case qui ne tient pas."""
    db = _State()
    brut = layout_par_defaut()
    scene = brut["scenes"][0]
    scene["elements"]["meme"]["wally_visible"] = True
    scene["elements"]["bingo"]["wally_visible"] = False
    await enregistrer_layout(db, brut)
    # Vraiment passé par le JSON de `bot_state`, pas seulement par la fusion.
    assert '"wally_visible"' in db.rows[LAYOUT_KEY]
    json.loads(db.rows[LAYOUT_KEY])
    relu = (await charger_layout(db))["scenes"][0]["elements"]
    assert relu["meme"]["wally_visible"] is True
    assert relu["bingo"]["wally_visible"] is False


# ── La page ─────────────────────────────────────────────────────────────────

def _bloc(source: str, entete: str) -> str:
    i = source.index(entete)
    return source[i:source.index("\n  }", i)]


def test_leffacement_de_lavatar_ne_lit_plus_solo():
    """L'écrivain unique de `widget-on` doit se fonder sur le nouveau réglage.
    Tant qu'il lisait `soloEnPlace()`, un meme réglé pour garder Wally l'effaçait
    quand même — la moitié de la séparation aurait manqué."""
    src = _JS.read_text(encoding="utf-8")
    i = src.index('classList.toggle("widget-on"')
    fenetre = src[i:i + 200]
    assert "masqueurEnPlace()" in fenetre
    assert "soloEnPlace()" not in fenetre


def test_la_file_dattente_lit_toujours_solo():
    """L'autre moitié : `solo` garde son sens. Le brancher lui aussi sur
    `wally_visible` ferait cohabiter deux cartes exclusives par-dessus l'autre."""
    assert "if (soloEnPlace()) return false;" in _JS.read_text(encoding="utf-8")


def test_le_champ_absent_retombe_sur_lancien_comportement():
    """Le layout servi peut ne pas porter le champ — une page ouverte pendant
    qu'un vieux JSON est encore en base. Le repli doit être `solo`, et non
    « Wally reste » : l'overlay se mettrait à afficher l'avatar par-dessus tous
    les memes, en plein live, sans que personne n'ait rien réglé."""
    bloc = _bloc(_JS.read_text(encoding="utf-8"), "function masqueWally(kind)")
    assert "el.wally_visible === undefined" in bloc
    assert "el.solo !== false" in bloc


def test_un_element_masque_nefface_pas_wally():
    """Même garde que `estSolo()` : un élément masqué n'occupe rien, l'effacer
    ferait perdre Wally sans rien montrer à la place."""
    bloc = _bloc(_JS.read_text(encoding="utf-8"), "function masqueWally(kind)")
    assert "el.hidden" in bloc


# ── Le panneau ──────────────────────────────────────────────────────────────

def test_le_panneau_offre_la_case_et_ecrit_le_champ():
    src = _JS_ADMIN.read_text(encoding="utf-8")
    assert "Wally reste visible" in src
    assert "element.wally_visible = coche.checked;" in src
    # Une modification non signalée resterait en brouillon sans que le compteur
    # de la barre de publication ne bouge : on croirait avoir tout publié.
    i = src.index("element.wally_visible = coche.checked;")
    assert "marquerModifie()" in src[i:i + 120]


def test_la_case_montre_le_comportement_reel_dun_layout_sans_le_champ():
    """Même repli que la page. Sans lui, un modèle d'avant le champ afficherait
    toutes les cases décochées — y compris pour le bingo, qui n'a jamais effacé
    Wally — et le premier clic aurait changé un comportement qu'on croyait
    lire."""
    bloc = _bloc(_JS_ADMIN.read_text(encoding="utf-8"), "function gardeWally(element)")
    assert "element.wally_visible === undefined" in bloc
    assert "element.solo === false" in bloc
