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
    pas — c'est le HTML qui porte les conteneurs.

    Borné au CORPS de la page : `[data-element="…"]` sert aussi de sélecteur
    CSS, et compter ces occurrences-là ferait passer une clé qui n'a qu'une
    règle de style et aucun conteneur — soit exactement le trou cherché.
    """
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    corps = html.split("</style>", 1)[-1]
    assert "<body" in corps, "découpage du corps raté : la page a changé de forme"
    declares = set(re.findall(r'<div data-element="([^"]+)"', corps))
    manquants = set(ELEMENTS) - declares
    assert not manquants, f"conteneurs absents d'overlay.html : {sorted(manquants)}"
    inconnus = declares - set(ELEMENTS)
    assert not inconnus, f"conteneurs sans élément au modèle : {sorted(inconnus)}"


# Les objets de builders, et la profondeur d'indentation de leurs méthodes.
_SOURCES_BUILDERS = (
    ("overlay.js", "const BUILDERS = {"),
    ("overlay_apex.js", "window.APEX_BUILDERS = {"),
)
# Une méthode d'objet : `nom(p) {`, à quatre espaces. Le corps d'un builder est
# indenté plus profond, un `if (…) {` ne colle pas (espace avant la parenthèse).
_METHODE = re.compile(r"^ {4}([A-Za-z_]\w*)\s*\(\s*\w*\s*\)\s*\{\s*$")


def _cles_builders(fichier: str, marqueur: str) -> set[str]:
    """Les clés d'un objet de builders, lues dans le source.

    Bornée au bloc : les fonctions déclarées ailleurs dans le fichier ne sont
    pas des `kind`.
    """
    lignes = (_STATIC / fichier).read_text(encoding="utf-8").splitlines()
    debut = next((i for i, l in enumerate(lignes) if l.strip() == marqueur), None)
    assert debut is not None, f"`{marqueur}` introuvable dans {fichier}"
    cles = set()
    for ligne in lignes[debut + 1:]:
        if ligne.rstrip() == "  };":          # fin de l'objet
            break
        trouve = _METHODE.match(ligne)
        if trouve:
            cles.add(trouve.group(1))
    return cles


def test_tout_kind_rendu_par_la_page_est_placable():
    """Le contrôle qui manquait, et qui a laissé passer les huit panneaux Apex.

    Comparer `ELEMENTS` au HTML ne prouve rien : les deux listes sont écrites à
    la main, du même geste, et un `kind` oublié des deux est invisible. La seule
    source qui ne ment pas, c'est le code qui RESTITUE — `BUILDERS`, fusionné
    avec `APEX_BUILDERS` (`overlay.js`, `Object.assign`). Un `kind` rendu mais
    absent d'`ELEMENTS` n'est pas seulement mal placé : il n'est PAS RÉGLABLE,
    `appliquer()` n'itérant que sur `ELEMENTS`.
    """
    rendus = set()
    for fichier, marqueur in _SOURCES_BUILDERS:
        cles = _cles_builders(fichier, marqueur)
        # Sanity : une regex qui ne colle plus rendrait le test vert à vide.
        assert len(cles) >= 8, f"extraction suspecte dans {fichier} : {sorted(cles)}"
        rendus |= cles
    assert {"coinflip", "apex_rank", "clip_top"} <= rendus, sorted(rendus)

    absents = rendus - set(ELEMENTS)
    assert not absents, (
        f"`kind` rendus par la page mais absents d'`ELEMENTS` : {sorted(absents)}. "
        "Ils sortiraient dans un conteneur improvisé, et resteraient à jamais "
        "hors de portée du panneau de mise en scène."
    )


def test_la_bulle_ne_rogne_jamais_ses_pseudo_elements():
    """`overflow: hidden` sur la bulle rognerait sa pointe.

    Elle est dessinée par `::before`/`::after` ; la pointe n'a JAMAIS été rendue
    pendant des semaines pour cette raison exacte (bulles BD, 2026-08-13). Le
    garde-fou anti-débordement vit sur `#bubble-text`, un enfant.

    Le contrôle porte sur la bulle ET sur ses ANCÊTRES de placement : un
    `overflow` sur `[data-element]` rognerait la pointe exactement pareil, et
    la règle est désormais à deux pas de la bulle dans le même fichier.
    """
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")
    selecteurs = (r"#bubble", r"\[data-element\]", r'\[data-element="bubble"\]')
    for selecteur in selecteurs:
        blocs = re.findall(rf"\n\s*{selecteur}\s*\{{(.*?)\}}", html, re.S)
        assert blocs, f"règle `{selecteur} {{ … }}` introuvable : la regex ne colle plus"
        for bloc in blocs:
            assert "overflow" not in bloc, (
                f"`overflow` sur `{selecteur}` rogne la pointe de la bulle"
            )
