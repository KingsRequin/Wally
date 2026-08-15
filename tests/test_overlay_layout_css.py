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


# ── Les deux tests qui suivent vont par PAIRE. Ne pas en supprimer un ────────
#
# `test_tout_kind_rendu_par_la_page_est_placable` vérifie que tout ce que la
# page RESTITUE est plaçable — c'est le filet qui manquait quand les huit
# panneaux Apex sont restés hors du modèle.
#
# `test_les_builders_restent_dans_la_forme_que_l_extraction_sait_lire` vérifie
# que le premier VOIT bien tout. Il n'est pas une redondance : le premier
# repose sur une lecture du source par expression régulière, qui ne reconnaît
# qu'une seule façon d'écrire une entrée. Un widget écrit `nom: (p) => {`,
# `async nom(p) {` ou `nom({ x, y }) {` ne serait pas extrait — donc jamais
# comparé à `ELEMENTS` — et le premier test resterait VERT pendant qu'un widget
# réel serait inatteignable depuis le panneau de mise en scène. Exactement le
# trou qu'il est censé fermer.
#
# Le renversement est ce qui compte : plutôt que d'espérer que l'extraction
# voie toutes les formes, on INTERDIT celles qu'elle ne voit pas. Un
# contributeur qui écrit un widget autrement obtient un échec explicite, avec la
# marche à suivre, au lieu d'un silence.

# Les objets de builders, et le marqueur qui ouvre chacun.
_SOURCES_BUILDERS = (
    ("overlay.js", "const BUILDERS = {"),
    ("overlay_apex.js", "window.APEX_BUILDERS = {"),
)
# La forme canonique d'une entrée : `nom(p) {`, à quatre espaces. Le corps d'un
# builder est indenté plus profond, un `if (…) {` ne colle pas (espace avant la
# parenthèse).
_METHODE = re.compile(r"^ {4}([A-Za-z_]\w*)\s*\(\s*\w*\s*\)\s*\{\s*$")
# Ce qu'on tolère d'autre à la profondeur des entrées : leur accolade fermante,
# et les commentaires qui les présentent.
_FERMETURE = re.compile(r"^ {4}\},?$")
_COMMENTAIRE = re.compile(r"^ {4}(//|/\*|\*)")
# Uniquement pour NOMMER la forme fautive dans le message d'échec. Le refus,
# lui, ne dépend pas de cette liste : est refusé tout ce qui n'est pas canonique.
_FORMES = (
    ("=>", "fonction fléchée, du genre `nom: (p) => {`"),
    ("async ", "méthode `async`"),
    ("function", "`function` explicite"),
    ("...", "propriété étalée (`...`)"),
    (":", "clé suivie de deux-points"),
)


def _lignes_bloc(fichier: str, marqueur: str) -> list[str]:
    """Les lignes d'un objet de builders, marqueur et accolade finale exclus.

    Bornée au bloc : ce qui est déclaré ailleurs dans le fichier n'est pas une
    entrée de l'objet.
    """
    lignes = (_STATIC / fichier).read_text(encoding="utf-8").splitlines()
    debut = next((i for i, l in enumerate(lignes) if l.strip() == marqueur), None)
    assert debut is not None, f"`{marqueur}` introuvable dans {fichier}"
    fin = next((i for i, l in enumerate(lignes[debut + 1:], debut + 1)
                if l.rstrip() == "  };"), None)
    assert fin is not None, f"fin de `{marqueur}` introuvable dans {fichier}"
    return lignes[debut + 1:fin]


def _cles_builders(fichier: str, marqueur: str) -> set[str]:
    """Les clés d'un objet de builders, lues dans le source."""
    return {m.group(1) for m in
            (_METHODE.match(l) for l in _lignes_bloc(fichier, marqueur)) if m}


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


def test_les_builders_restent_dans_la_forme_que_l_extraction_sait_lire():
    """Le garde du test précédent : on interdit ce que l'extraction ne voit pas.

    Une entrée écrite autrement ne serait pas extraite, donc jamais comparée à
    `ELEMENTS` — et le contrôle d'à côté resterait vert pendant qu'un widget
    réel serait inatteignable. Le compte des entrées ne dit rien de ce qui
    manque : trente clés peuvent correspondre pendant qu'une trente-et-unième
    est ignorée en silence.

    Deux signaux indépendants sur les mêmes lignes :
      1. à la profondeur des entrées, on n'accepte QUE la forme canonique
         (plus les fermetures et les commentaires) ;
      2. chaque entrée ouvre et ferme à cette profondeur — autant de `}` que de
         `nom(p) {`. Une signature étalée sur plusieurs lignes, que la règle 1
         ne verrait pas, déséquilibre ce compte.
    """
    for fichier, marqueur in _SOURCES_BUILDERS:
        lignes = _lignes_bloc(fichier, marqueur)
        assert lignes, f"bloc vide dans {fichier} : le découpage ne colle plus"
        entrees, fermetures, suspectes = 0, 0, []
        for numero, ligne in enumerate(lignes, 1):
            if not ligne.strip():
                continue
            indentation = len(ligne) - len(ligne.lstrip())
            # Moins indenté que les entrées : une entrée cachée là échapperait
            # à toutes les règles qui suivent.
            assert indentation >= 4, (
                f"{fichier}, ligne {numero} : indentation de {indentation} "
                f"espaces sous la profondeur des entrées — {ligne.strip()!r}"
            )
            if indentation != 4:
                continue
            if _METHODE.match(ligne):
                entrees += 1
            elif _FERMETURE.match(ligne):
                fermetures += 1
            elif not _COMMENTAIRE.match(ligne):
                forme = next((nom for motif, nom in _FORMES if motif in ligne),
                             "forme inconnue")
                suspectes.append(f"ligne {numero} ({forme}) : {ligne.strip()!r}")

        assert not suspectes, (
            f"{fichier} — entrées que l'extraction des `kind` ne sait PAS lire :\n  "
            + "\n  ".join(suspectes)
            + "\n\nUne entrée sous cette forme n'est jamais comparée à `ELEMENTS` : "
            "le widget serait rendu, mais impossible à placer, et aucun test ne "
            "le dirait.\nDeux issues : réécrire l'entrée sous la forme canonique "
            "`nom(p) {` à quatre espaces, ou élargir `_METHODE` — et ce garde "
            "avec elle."
        )
        assert entrees == fermetures, (
            f"{fichier} : {entrees} entrées lues pour {fermetures} accolades "
            "fermantes à leur profondeur. Une entrée est écrite sous une forme "
            "que `_METHODE` ne reconnaît pas — une signature sur plusieurs "
            "lignes, par exemple. Voir la note en tête de fichier."
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
