"""La liste des fichiers qui composent l'empreinte de l'overlay.

OBS garde sa page en mémoire des heures. L'overlay interroge une empreinte du
contenu pour se recharger tout seul — mais un fichier absent de la liste ne
compte pas dedans : il est servi indéfiniment dans sa version du premier
chargement, et un correctif n'arrive jamais à l'écran.

Le défaut est passé DEUX fois : d'abord avec `overlay_apex.js` et les
bibliothèques de `vendor/`, puis avec `glitch.js`. Rien ne reliait la liste au
HTML, il fallait y penser. Ce test fait le lien.
"""
import re
from pathlib import Path

from bot.dashboard.routes.overlay import _OVERLAY_FILES, _STATIC_DIR


def test_tout_script_charge_par_la_page_compte_dans_l_empreinte():
    html = (_STATIC_DIR / "overlay.html").read_text(encoding="utf-8")
    charges = {m.removeprefix("/static/")
               for m in re.findall(r'src="(/static/[^"?]+\.js)"', html)}
    assert charges, "aucun script trouvé : la regex ne colle plus au HTML"

    oublies = charges - set(_OVERLAY_FILES)
    assert not oublies, (
        f"absents de `_OVERLAY_FILES` : {sorted(oublies)}. OBS resservirait "
        "indéfiniment leur première version."
    )


def test_les_fichiers_de_l_empreinte_existent():
    """Un nom mal orthographié compte comme absent, sans rien dire : le calcul
    avale l'erreur pour qu'un déploiement partiel ne fige pas la version."""
    manquants = [f for f in _OVERLAY_FILES if not (_STATIC_DIR / f).exists()]
    assert not manquants, f"introuvables dans `static/` : {manquants}"


def test_la_page_elle_meme_en_fait_partie():
    """Sans elle, une retouche de style pur ne déclencherait aucun rechargement."""
    assert "overlay.html" in _OVERLAY_FILES
