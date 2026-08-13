"""Greffe de la queue sur la bulle de parole.

Le raccord entre la queue et le contour de la bulle ne se voit qu'en zoomant :
un défaut y passe la revue et part en prod. Il en est parti un le 2026-08-13,
repéré par le propriétaire sur une capture agrandie.

Les deux invariants ci-dessous sont ceux qui avaient lâché. Aucun ne fige de
coordonnée : la queue peut être redessinée librement, tant que le raccord tient.
"""
import re
from pathlib import Path

_HTML = Path(__file__).resolve().parent.parent / "bot" / "dashboard" / "static" / "overlay.html"


def _regle_queue() -> str:
    """Le bloc CSS qui DESSINE la queue.

    Deux règles visent `#bubble.speech::after` : celle-ci et son miroir pour
    l'ancrage à droite, qui ne fait que repositionner. On retient celle qui
    porte le SVG.
    """
    html = _HTML.read_text(encoding="utf-8")
    blocs = [m.group(1) for m in
             re.finditer(r"#bubble\.speech::after\s*\{(.*?)\n    \}", html, re.S)]
    dessin = [b for b in blocs if "background-image" in b]
    assert len(dessin) == 1, f"attendu une seule règle porteuse du SVG, trouvé {len(dessin)}"
    return dessin[0]


def _chemins_svg(regle: str) -> list[str]:
    """Les attributs `d` des tracés du SVG de la queue, décodés."""
    from urllib.parse import unquote

    m = re.search(r'background-image:\s*url\("data:image/svg\+xml,([^"]+)"\)', regle)
    assert m, "SVG de la queue introuvable"
    return re.findall(r"d='([^']+)'", unquote(m.group(1)))


def test_aplat_et_trait_de_la_queue_partent_du_meme_point():
    """L'aplat de la queue efface le contour de la bulle sous la mouche ; les
    traits doivent le remplacer EXACTEMENT là. Quand l'aplat mordait 10 px plus
    loin que les traits, il effaçait du contour que rien ne reprenait : une
    encoche visible de chaque côté de la mouche."""
    chemins = _chemins_svg(_regle_queue())
    assert len(chemins) == 2, f"attendu un tracé d'aplat et un de trait, reçu {len(chemins)}"

    def bornes(d: str) -> tuple[str, str]:
        pts = re.findall(r"-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?", d)
        return pts[0], pts[-1]

    aplat, trait = (bornes(c) for c in chemins)
    assert aplat == trait, (
        f"l'aplat va de {aplat[0]} à {aplat[1]}, le trait de {trait[0]} à {trait[1]} : "
        "le contour serait effacé là où aucun trait ne le remplace"
    )


def test_la_greffe_suit_la_largeur_de_la_bulle():
    """La silhouette est en retrait d'un POURCENTAGE de la largeur (la marge qui
    empêche son trait d'être rogné par le viewBox). Ce retrait grandit donc avec
    la bulle : une greffe posée en pixels fixes tombe juste à une seule taille et
    flotte à toutes les autres."""
    html = _HTML.read_text(encoding="utf-8")
    # Les deux ancrages : la règle de base (`left`) et son miroir (`right`).
    offsets = re.findall(r"^\s+(?:left|right):\s*(calc\([^;]+\));", html, re.M)
    greffes = [o for o in offsets if "%" in o and "px" in o]
    assert len(greffes) >= 2, (
        f"les deux ancrages de la queue doivent se décaler en %, trouvé : {offsets}"
    )
