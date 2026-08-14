"""Grammaire d'animation de l'overlay.

Ces invariants ne se lisent pas dans le code : une courbe à dépassement posée
sur la mauvaise règle produit un CSS parfaitement valide, et le défaut ne se
voit qu'à l'œil, sur une sortie qui rebondit au lieu de s'en aller.

Aucune valeur n'est figée : les durées et les courbes peuvent bouger, seule la
grammaire est tenue.
"""
import re
from pathlib import Path

_HTML = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static" / "overlay.html"


def _css() -> str:
    """Le CSS, commentaires retirés : ils PARLENT des règles, ils n'en sont pas."""
    html = _HTML.read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    return re.sub(r"/\*.*?\*/", "", style, flags=re.S)


def _regle(css: str, selecteur: str) -> str:
    """Le corps d'une règle, le sélecteur pris en DÉBUT de ligne.

    Sans cette ancre, `.widget` attrapait `body[data-side="right"] .widget`,
    déclarée plus haut dans le fichier — le test lisait la mauvaise règle.
    """
    m = re.search(r"(?m)^\s*" + re.escape(selecteur) + r"\s*\{([^}]*)\}", css)
    assert m, f"règle `{selecteur}` introuvable"
    return m.group(1)


def test_une_sortie_ne_rebondit_pas():
    """Une transition déclarée sur la seule règle de base s'applique dans les
    DEUX sens. La courbe à dépassement `--ease-pop` s'y trouvait : la bulle et
    les widgets dépassaient puis revenaient EN PARTANT. Une sortie accélère et
    s'en va.

    L'état de repos porte donc les réglages de sortie, `.visible` ceux d'entrée.
    """
    css = _css()
    for base, actif in (("#bubble", "#bubble.visible"), (".widget", ".widget.visible")):
        sortie, entree = _regle(css, base), _regle(css, actif)
        assert "transition:" in sortie, f"`{base}` doit porter ses réglages de sortie"
        assert "transition:" in entree, (
            f"`{actif}` doit porter ses propres réglages d'entrée, sinon ceux de "
            "la sortie s'appliquent aussi à l'arrivée"
        )
        assert "--ease-pop" not in sortie, (
            f"`{base}` : la courbe à dépassement appartient à l'ENTRÉE. Déclarée "
            "ici, elle fait rebondir la sortie."
        )


def test_la_bulle_grandit_depuis_sa_queue():
    """Sans origine, elle se matérialise en son centre — elle apparaît à côté de
    Wally au lieu de sortir de sa bouche. L'origine suit donc l'ancrage."""
    css = _css()
    assert "transform-origin" in _regle(css, "#bubble"), "origine absente de `#bubble`"
    assert re.search(r'body\[data-side="right"\]\s+#bubble\s*\{[^}]*transform-origin', css), (
        "l'origine doit basculer avec l'ancrage : à droite, la queue change de côté"
    )


def test_la_cloture_du_duel_eteint_le_perdant():
    """La couleur de victoire ne peut pas, à elle seule, dire qu'un duel est
    fini : le tableau colore déjà le meneur à chaque manche. Il faut donc que
    la clôture éteigne le perdant — c'est le seul contraste que le spectateur
    ne voit jamais en cours de duel.

    Le sélecteur peut changer ; ce qui est tenu, c'est qu'une règle de clôture
    du tableau baisse une opacité."""
    css = _css()
    cloture = re.findall(r"(?m)^\s*\.versus\.final[^{]*\{([^}]*)\}", css)
    assert cloture, "aucune règle de clôture sur le tableau du duel"
    estompe = [c for c in cloture if re.search(r"opacity:\s*0?\.\d", c)]
    assert estompe, f"la clôture ne baisse aucune opacité : {cloture}"


def test_aucune_barre_n_anime_sa_largeur():
    """`width` refait la mise en page à chaque image, sur le thread principal.
    `transform` est composé par le GPU : la barre continue de glisser même quand
    le thread principal hoquette — ce qui arrive précisément quand un lot
    d'événements SSE tombe."""
    css = _css()
    fautives = re.findall(r"transition:[^;]*\bwidth\b[^;]*;", css)
    assert not fautives, f"barres animées en largeur : {fautives}"
