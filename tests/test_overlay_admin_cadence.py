"""Les réglages de scène dans le panneau de mise en scène.

Ce que ces tests figent, et qui n'a pas changé depuis qu'ils ne portaient que
sur la cadence du rotateur :

  1. Le panneau ne propose QUE des réglages qui existent dans le modèle. Un
     champ affiché sans exister laisse saisir une valeur que le serveur ramène
     en silence — on croit avoir réglé, rien ne bouge, et rien ne le dit.
  2. Les champs ne s'affichent que pour leur porteur. « Durée d'affichage » sur
     un avatar, qui vit en permanence, est un réglage qu'aucun code ne lit.
  3. Rien ne s'écrit sur un élément qui ne porte pas le champ, même par un
     chemin détourné : un champ caché reste dans le document.

Ce qui a changé le 2026-08-21 : le panneau ne RECOPIE plus les bornes. Elles
viennent du GET (`portees`), avec les portées et le catalogue d'animations. Le
contrôle passe donc de l'ÉGALITÉ des deux tables à l'INCLUSION de ce que le
panneau montre dans ce que le modèle déclare — le modèle en porte trente-six,
le panneau n'en montre qu'une poignée à la fois.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from bot.core.overlay_layout import (
    CHAMPS_CHOIX, CHAMPS_PROPRES, CHAMPS_UNIVERSELS, ELEMENTS)

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
_JS = (_STATIC / "overlay_admin.js").read_text(encoding="utf-8")

_PRELUDE = """
global.window = global;
global.navigator = {};
global.window.localStorage = {
  getItem: function () { return null; },
  setItem: function () {},
  removeItem: function () {},
};
require(%s);
require(%s);
const OA = window.OverlayAdmin;
""" % (json.dumps(str(_STATIC / "overlay_layout.js")),
       json.dumps(str(_STATIC / "overlay_admin.js")))

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0


def _table_du_panneau() -> dict:
    """`CHAMPS` tel que le navigateur le verra : la table de PRÉSENTATION."""
    r = subprocess.run(
        ["node", "-e", _PRELUDE + "console.log(JSON.stringify(OA.CHAMPS));"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_le_panneau_ne_propose_aucun_reglage_inconnu_du_modele():
    """L'INCLUSION, pas l'égalité. Un champ que le panneau montre sans qu'il
    existe côté serveur laisse saisir une valeur qui sera ramenée en silence :
    on croit avoir réglé, rien ne bouge, et rien ne le dit."""
    connus = set(CHAMPS_UNIVERSELS)
    for champs in CHAMPS_PROPRES.values():
        connus |= set(champs)
    for champs in CHAMPS_CHOIX.values():
        connus |= set(champs)
    inconnus = set(_table_du_panneau()) - connus
    assert not inconnus, f"le panneau propose des réglages fantômes : {inconnus}"


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_le_panneau_ne_recopie_plus_les_bornes_du_serveur():
    """Deux tables qui disent la même chose divergent au premier ajustement.
    La table locale ne garde que ce que le serveur NE PEUT PAS dire : le
    libellé français, le pas de manipulation, l'infobulle."""
    for nom, pres in _table_du_panneau().items():
        assert "mini" not in pres and "maxi" not in pres, (
            f"`{nom}` redit des bornes que le serveur sert déjà")
        assert pres.get("label"), f"`{nom}` sans libellé lisible"


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_chaque_reglage_du_modele_est_atteignable_depuis_le_panneau():
    """Le trou symétrique, et le plus coûteux : un champ que le modèle porte
    mais que le panneau ne montre nulle part est un réglage inatteignable — il
    existe, il est validé, il est rangé, et personne ne peut y toucher."""
    connus = set(CHAMPS_UNIVERSELS)
    for champs in CHAMPS_PROPRES.values():
        connus |= set(champs)
    for champs in CHAMPS_CHOIX.values():
        connus |= set(champs)
    manquants = connus - set(_table_du_panneau())
    assert not manquants, f"réglages inatteignables depuis le panneau : {manquants}"


@pytest.mark.skipif(_SANS_NODE, reason="node absent")
def test_les_libelles_sont_en_francais_et_portent_leur_unite():
    """Le propriétaire règle ça en plein live : « duree » et un nombre nu le
    laisseraient deviner s'il s'agit de secondes, de degrés ou de pixels."""
    avec_unite = {"duree", "pause", "delai", "anim_duree", "rotation",
                  "largeur_max"}
    for nom, pres in _table_du_panneau().items():
        assert pres.get("aide"), f"le champ `{nom}` n'a pas d'explication"
        assert pres["label"] == pres["label"].strip()
        if nom in avec_unite:
            assert pres.get("unite"), f"`{nom}` ne dit pas son unité"


def test_un_reglage_est_cache_hors_de_son_porteur():
    """`hidden` sur le bloc, pas seulement un champ grisé : un réglage visible
    que rien ne lit est une promesse fausse."""
    assert "champ.bloc.hidden = !porte" in _JS


def test_un_reglage_refuse_decrire_sur_un_element_qui_ne_le_porte_pas():
    """La garde est au POINT D'ÉCRITURE et pas au rendu : un bloc caché reste
    dans le document, et un navigateur qui garde le focus — ou un script —
    poserait `duree` sur un avatar qui n'en a pas. Le modèle la jetterait à
    l'enregistrement, mais le panneau aurait compté une modification et le pied
    aurait annoncé un changement qui n'a jamais eu lieu.

    Les DEUX portes d'écriture sont gardées : les champs numériques passent par
    `ecrire()`, les booléens et les choix par `ecrireBrut()`. Une seule des deux
    gardée laisserait la moitié des réglages sans protection."""
    assert "function portePar(element, nom)" in _JS
    for porte in ("function ecrire(def, valeur, proprietaire) {",
                  "function ecrireBrut(nom, valeur) {"):
        bloc = _JS[_JS.index(porte):_JS.index(porte) + 700]
        assert "portePar(element," in bloc, f"porte non gardée : {porte}"


# ── Le sélecteur d'animation (2026-08-21) ───────────────────────────────────

def test_le_selecteur_est_un_menu_flottant_et_non_un_select():
    """Un `<select>` natif ne montre ni recherche ni aperçu, et quatre-vingt-
    dix-sept options en dix familles ne s'y parcourent pas.

    `ovl-menu-flottant` est INDISPENSABLE : sans elle, `.ovl-menu` reste en
    `position: absolute; top: 100%; right: 6px` et le `left`/`top` en pixels
    calculé au moment de l'ouverture ne vise plus rien."""
    assert "function ouvrirSelecteurAnim" in _JS
    bloc = _JS[_JS.index("function ouvrirSelecteurAnim"):]
    assert "ovl-menu-flottant" in bloc[:1500]


def test_le_selecteur_choisit_son_cote_a_louverture():
    """Piège déjà payé sur ce panneau : un panneau volant ancré en dur sort de
    l'écran une fois sur deux, la barre passant à la ligne selon la largeur."""
    bloc = _JS[_JS.index("function ouvrirSelecteurAnim"):]
    fin = bloc.index("\n  }\n")
    assert "getBoundingClientRect" in bloc[:fin]
    assert "window.innerHeight" in bloc[:fin], "le sens vertical doit se choisir aussi"


def test_lapercu_se_nettoie_par_un_minuteur_et_non_par_animationend():
    """Une vignette relancée pendant son animation déclenche `animationcancel`
    et non `animationend` ; et si `animate.min.css` n'était pas servi,
    l'événement n'arriverait jamais — la classe resterait posée pour toujours.
    Piège déjà payé sur l'image de la galerie, dans `overlay.js`."""
    debut = _JS.index("function jouer(nom)")
    corps = _JS[debut:_JS.index("const entrees = []", debut)]
    # Commentaires retirés : celui de cette fonction NOMME `animationend` pour
    # dire précisément qu'on ne s'en sert pas. Chercher dans le texte brut
    # ferait échouer le test sur son propre avertissement.
    code = re.sub(r"//.*", "", corps)
    assert "setTimeout" in code
    assert "animationend" not in code


def test_la_recherche_porte_sur_le_nom_la_cle_et_la_famille():
    """On connaît l'un ou l'autre selon qu'on cherche « fondu », « fadeInUp » ou
    « glissement ». Même parti pris que le filtre de la liste des éléments."""
    bloc = _JS[_JS.index("groupe.boutons.push("):]
    assert "nomAnimation(nom)" in bloc[:400]
    assert "famille" in bloc[:400]


def test_le_catalogue_danimations_nest_pas_recopie_en_javascript():
    """Il vient du serveur. Deux listes divergent à la première mise à jour
    d'animate.css — et la moitié des choix ne feraient alors plus rien."""
    assert "etat.animations" in _JS
    # Aucune LISTE d'animations en dur. Les noms techniques cités dans les
    # commentaires ne comptent pas : ce qu'on traque, c'est un second catalogue
    # qui divergerait du premier. Le code, commentaires retirés, ne doit
    # contenir aucun nom d'animation directionnel.
    code = re.sub(r"//.*", "", _JS)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    for nom in ("fadeInUpBig", "bounceInLeft", "zoomInDown", "slideOutRight",
                "backInUp", "rotateInDownLeft"):
        assert nom not in code, f"catalogue recopié en JavaScript : {nom}"


def test_le_dashboard_sert_animate_css_pour_lapercu():
    """Sans cette feuille, `animate__zoomInDown` ne désigne rien et la vignette
    reste immobile : on choisirait une animation sur son nom seul, ce que le
    sélecteur existe précisément pour éviter."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    # Les BALISES, pas le texte : les commentaires alentour nomment les deux
    # feuilles, et une recherche naïve trouverait d'abord l'explication.
    liens = re.findall(r'<link[^>]+href="(/static/[^"]+\.css[^"]*)"', html)
    assert any(l.startswith("/static/animate.min.css") for l in liens), (
        "animate.css n'est pas servie au dashboard : la vignette d'aperçu "
        "resterait immobile")
    rang = [i for i, l in enumerate(liens)]
    i_anim = next(i for i, l in enumerate(liens) if "animate.min.css" in l)
    i_style = next(i for i, l in enumerate(liens) if "style.css" in l)
    assert i_anim < i_style, (
        "animate.css doit être déclarée AVANT le style du dashboard, qui doit "
        "l'emporter")


# ── L'inclinaison dans la géométrie du panneau ──────────────────────────────

def test_la_geometrie_tient_compte_de_linclinaison():
    """Un rectangle tourné déborde de son propre cadre. Sans ce calcul, le
    détecteur de chevauchement laisse passer deux éléments inclinés qui se
    recouvrent vraiment, et les poignées passent au travers de l'élément
    qu'elles entourent."""
    bloc = _JS[_JS.index("function geometrie(cle, element, W, H)"):]
    fin = bloc.index("\n  }\n")
    assert "Math.cos" in bloc[:fin] and "Math.sin" in bloc[:fin]


def test_le_point_dancrage_ne_bouge_pas_avec_linclinaison():
    """C'est ce qui laisse tout le glisser intact : la rotation est CENTRÉE, le
    point d'ancrage reste où il est, et `ax`/`ay` ne subissent pas le calcul de
    la boîte englobante."""
    bloc = _JS[_JS.index("function geometrie(cle, element, W, H)"):]
    fin = bloc.index("\n  }\n")
    corps = bloc[:fin]
    apres_rot = corps[corps.index("if (rot) {"):]
    assert "ax =" not in apres_rot and "ay =" not in apres_rot


# ── La propagation entre scènes ─────────────────────────────────────────────

def test_laspect_se_propage_mais_pas_le_rythme():
    """Le placement et l'aspect voyagent d'une scène à l'autre, comme la taille.
    Les durées et les animations restent : une scène de fin peut vouloir des
    passages plus longs qu'une scène de jeu — c'est tout l'intérêt de les avoir
    par scène."""
    r = subprocess.run(
        ["node", "-e", _PRELUDE + "console.log(JSON.stringify(OA.CHAMPS_PROPAGES));"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    propages = set(json.loads(r.stdout))
    assert {"opacite", "rotation", "miroir", "largeur_max"} <= propages
    assert not ({"duree", "delai", "anim_entree", "anim_sortie",
                 "anim_insistance", "anim_duree"} & propages)


def test_les_bornes_de_saisie_suivent_lelement_courant():
    """Le défaut vu à l'écran, invisible en test unitaire : les gestionnaires de
    `champNumerique` capturent la référence du tableau `def` dans leur closure.
    Lui en SUBSTITUER un autre au rendu laisse la saisie bornée sur les valeurs
    de construction — une inclinaison de 12° était rangée à 1, le pied annonçait
    « inclinaison 0° → 1° », et rien ne disait pourquoi.

    On mute donc le tableau, on ne le remplace pas."""
    bloc = _JS[_JS.index("champ.input.min = String(auto"):]
    fin = bloc.index("if (document.activeElement")
    corps = bloc[:fin]
    assert "champ.def[2]" in corps and "champ.def[3]" in corps
    assert "champ.def = [" not in corps, (
        "remplacer le tableau casse la closure des gestionnaires")
