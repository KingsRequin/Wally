"""Contrat entre `overlay.html` et `overlay.js`.

Le JS attrape ses éléments par `getElementById` au chargement du module. Si un
`id` disparaît du HTML — renommé, déplacé, supprimé pendant une retouche de
style — l'appel rend `null` et la première écriture dans la bulle lève. Rien ne
le signale côté serveur : l'overlay reste muet pendant tout le live, et OBS
n'affiche pas la console.

Le test ne fige aucune valeur : il vérifie seulement que tout `id` interrogé par
le JS existe côté HTML.
"""
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "bot" / "dashboard" / "static"


def test_tout_id_interroge_par_le_js_existe_dans_le_html():
    js = (_STATIC / "overlay.js").read_text(encoding="utf-8")
    html = (_STATIC / "overlay.html").read_text(encoding="utf-8")

    interroges = set(re.findall(r'getElementById\(\s*["\']([^"\']+)["\']', js))
    declares = set(re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', html))

    # Sanity : sans ça, une regex cassée rendrait le test vert à vide.
    assert "bubble" in interroges

    assert not (interroges - declares), (
        f"ids absents de overlay.html : {sorted(interroges - declares)}"
    )
