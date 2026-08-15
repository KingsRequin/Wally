"""Les deux ex-sources OBS vivent DANS la page principale.

Le rotateur de memes et l'image de la galerie ont eu chacun leur page pendant
des mois (`/overlay-rotation`, `/overlay-image`). Ils étaient donc réglables
depuis le panneau de mise en scène — position, ancrage, échelle, masquage —
sans que rien ne s'affiche jamais dans leur zone : on plaçait un carré vide.

Leur contenu a été porté dans `overlay.html` + `overlay.js` le 2026-08-15. Rien
n'empêche un remaniement de les en ressortir sans bruit : ces contrôles sont
mécaniques, ils échouent le jour où la page cesse de porter la boucle.

Ils ne figent aucune valeur d'affichage — seulement le fait que la page
s'adresse aux bonnes routes, dans les bons conteneurs, avec ses deux garde-fous
de production.
"""
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
_JS = (_STATIC / "overlay.js").read_text(encoding="utf-8")
_HTML = (_STATIC / "overlay.html").read_text(encoding="utf-8")
_CORPS = _HTML.split("</style>", 1)[-1]


def _conteneur(cle: str) -> str:
    """Le contenu du conteneur d'un élément, dans le CORPS de la page."""
    debut = _CORPS.index(f'<div data-element="{cle}">')
    profondeur = 0
    for m in re.finditer(r"<div\b|</div>", _CORPS[debut:]):
        profondeur += 1 if m.group() == "<div" else -1
        if profondeur == 0:
            return _CORPS[debut:debut + m.end()]
    raise AssertionError(f"conteneur `{cle}` non refermé")


# ── le rotateur de memes ────────────────────────────────────────────────────

def test_la_page_principale_interroge_la_liste_des_memes():
    """Sans cet appel, la zone `rotator` reste un rectangle vide qu'on peut
    placer et dimensionner — exactement l'absurdité qu'on a corrigée."""
    assert "/api/public/rotation" in _JS
    assert "/api/public/meme/" in _JS


def test_le_rotateur_a_son_cadre_dans_le_conteneur_de_son_element():
    """Et pas ailleurs : c'est le conteneur qui porte la place, l'échelle et
    l'empilement réglés. Un cadre posé hors de lui s'afficherait en plein
    écran, comme dans sa page d'origine où il était seul."""
    dedans = _conteneur("rotator")
    assert 'id="rotateur"' in dedans
    assert 'id="rotateur-image"' in dedans
    assert 'id="rotateur-video"' in dedans


def test_le_rotateur_cesse_dinsister_apres_trois_echecs():
    """Garde-fou payé en production : trois échecs d'affilée ne désignent plus
    des fichiers fautifs mais un serveur absent (un rebuild dure ~15 s).
    Continuer à écarter les médias fautifs viderait la bibliothèque entière en
    quelques secondes, et la zone perdrait l'autonomie qui fait son intérêt."""
    assert "echecsDaffilee" in _JS
    assert re.search(r"echecsDaffilee\s*<\s*3", _JS), (
        "le plafond de trois échecs a disparu du rotateur"
    )


def test_le_rotateur_prend_sa_cadence_du_reglage_de_la_scene():
    """Durée d'affichage et pause étaient figées dans le code, puis lues dans
    l'URL de la source OBS — qui n'existe plus. Elles vivent maintenant dans le
    modèle, et `appliquerReglage` est rappelée à chaque publication du panneau :
    c'est ce qui les fait suivre SANS recharger la page."""
    corps = _JS[_JS.index("function appliquerReglage"):]
    corps = corps[:corps.index("\n    }")]
    assert "el.duree" in corps and "el.pause" in corps, (
        "la cadence ne vient plus du réglage de la scène"
    )


def test_la_cadence_du_rotateur_ne_vient_plus_de_lurl():
    """Deux sources pour une même valeur, et c'est celle du panneau qui
    écraserait l'autre au premier chargement du layout : un réglage d'URL qui
    ne tient pas vaut moins qu'un réglage d'URL absent."""
    assert 'nombre("duree"' not in _JS
    assert 'nombre("pause"' not in _JS


def test_le_rotateur_est_coupe_par_le_reglage_de_la_scene():
    """Masqué, il ne doit ni s'afficher ni continuer à télécharger des médias
    pour personne : un `display: none` sur le conteneur ne couperait que
    l'affichage, et le trafic passerait inaperçu."""
    assert "ROTATEUR.appliquerReglage(reglages.rotator)" in _JS
    assert "IMAGE.appliquerReglage(reglages.image)" in _JS


# ── l'image de la galerie ───────────────────────────────────────────────────

def test_la_page_principale_ecoute_le_flux_des_images():
    assert "/api/public/sse/overlay-image" in _JS
    assert "show_image" in _JS


def test_limage_a_son_cadre_dans_le_conteneur_de_son_element():
    dedans = _conteneur("image")
    assert 'id="image-galerie"' in dedans
    assert 'id="image-galerie-img"' in dedans
    assert 'id="image-galerie-credit"' in dedans


def test_les_animations_configurables_sont_servies_a_la_page():
    """Le nom de l'animation vient de la configuration (`animation_in`). Sans
    la feuille, la classe ne désigne rien : l'image apparaîtrait sèchement et,
    dans la version d'origine, ne partirait JAMAIS — elle attendait un
    `animationend` qui n'arrivait pas."""
    assert 'href="/static/animate.min.css"' in _HTML
    assert (_STATIC / "animate.min.css").exists()

    from bot.dashboard.routes.overlay import _OVERLAY_FILES
    assert "animate.min.css" in _OVERLAY_FILES, (
        "hors de l'empreinte, OBS garderait sa copie du fichier pour toujours"
    )


def test_le_flux_des_images_passe_par_la_reconnexion_commune():
    """`EventSource.onerror` retombe à CHAQUE reconnexion, y compris normale :
    ce n'est pas une panne. La page d'origine armait pour ça un
    `location.reload()` de 30 s qu'elle devait désamorcer à `onopen`, sous
    peine d'empiler les rechargements pendant une coupure.

    Le portage n'a pas recopié ce montage : il branche le flux sur `connect()`,
    qui rouvre avec un backoff. Le contrôle porte sur l'invariant qui le
    garantit — UN seul `new EventSource` dans le fichier, donc aucun flux qui
    gère ses erreurs dans son coin.
    """
    assert re.search(r'connect\(\s*"/api/public/sse/overlay-image"', _JS), (
        "le flux des images n'utilise plus la reconnexion commune"
    )
    assert _JS.count("new EventSource") == 1, (
        "un flux ouvert hors de `connect()` refait sa propre gestion d'erreur"
    )


# ── les deux anciennes pages ────────────────────────────────────────────────

def test_lancienne_source_de_limage_dit_ce_quelle_est_devenue():
    """Elle reste servie — elle est peut-être encore dans une scène OBS — mais
    quelqu'un qui l'ouvre doit lire quoi faire à la place."""
    texte = (_STATIC / "overlay_image.html").read_text(encoding="utf-8")
    assert "OBSOLÈTE" in texte, "la page ne dit pas qu'elle est remplacée"
    assert "EN DOUBLE" in texte, "la page ne prévient pas du doublon"


def test_lancienne_page_du_rotateur_ne_fait_plus_tourner_de_memes():
    """Sa boucle est retirée, pas seulement dépréciée : tant que les deux
    sources tournaient, les memes s'affichaient en double."""
    texte = (_STATIC / "overlay_rotation.html").read_text(encoding="utf-8")
    assert "/api/public/rotation" not in texte
    assert "/api/public/meme/" not in texte
    assert "<script" not in texte, "la page ne doit plus rien exécuter"


def test_lancienne_page_du_rotateur_affiche_son_remplacement():
    """À L'ÉCRAN, et pas seulement dans un commentaire HTML : cette page est
    lue dans une source navigateur OBS, où personne ne voit le source. Un 404
    muet y mettrait un rectangle vide, et on l'apprendrait en plein live."""
    texte = (_STATIC / "overlay_rotation.html").read_text(encoding="utf-8")
    corps = texte[texte.index("<body"):]
    assert "remplacée" in corps
    assert "/overlay-&lt;scène&gt;" in corps, (
        "la page ne dit pas quelle URL utiliser à la place"
    )
