"""Le modèle et la page doivent nommer les mêmes éléments.

Une clé ajoutée dans `ELEMENTS` sans conteneur dans la page ne serait jamais
rendue, et personne ne le verrait avant un live. Le contrôle est mécanique.
"""
import re
from pathlib import Path

from bot.core.overlay_layout import ANCRAGES, ELEMENTS

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"


def test_chaque_element_a_son_ancrage_declare_dans_le_js():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    for ancrage in ANCRAGES:
        assert f'"{ancrage}"' in js, f"ancrage absent du JS : {ancrage}"


def test_chaque_element_du_modele_est_connu_de_la_page():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    for cle in ELEMENTS:
        assert f'"{cle}"' in js, f"élément absent du JS : {cle}"


def test_le_canvas_de_reference_est_bien_1920():
    js = (_STATIC / "overlay_layout.js").read_text(encoding="utf-8")
    assert "1920" in js


def test_chaque_element_du_modele_a_son_conteneur_dans_le_html():
    """La vraie panne silencieuse : un widget dont le conteneur n'existe pas
    n'apparaît nulle part, sans la moindre erreur. La liste du JS ne suffit
    pas — c'est le HTML qui porte les conteneurs."""
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    declares = set(re.findall(r'data-element="([^"]+)"', html))
    manquants = set(ELEMENTS) - declares
    assert not manquants, f"conteneurs absents d'overlay.html : {sorted(manquants)}"
    inconnus = declares - set(ELEMENTS)
    assert not inconnus, f"conteneurs sans élément au modèle : {sorted(inconnus)}"


def test_la_bulle_ne_rogne_jamais_ses_pseudo_elements():
    """`overflow: hidden` sur la bulle rognerait sa pointe.

    Elle est dessinée par `::before`/`::after` ; la pointe n'a JAMAIS été rendue
    pendant des semaines pour cette raison exacte (bulles BD, 2026-08-13). Le
    garde-fou anti-débordement vit sur `#bubble-text`, un enfant.
    """
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    bloc = re.search(r"\n\s*#bubble\s*\{(.*?)\}", html, re.S)
    assert bloc, "règle `#bubble { … }` introuvable : la regex ne colle plus"
    assert "overflow" not in bloc.group(1), (
        "`overflow` sur #bubble rogne la pointe de la bulle"
    )
