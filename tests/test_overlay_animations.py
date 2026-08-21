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


# ── Le catalogue servi au panneau (conception du 2026-08-21) ────────────────
#
# Il ne suffit pas qu'il soit bien formé : chaque nom doit correspondre à une
# CLASSE RÉELLE d'animate.css. Un nom sans classe donne un choix qui ne fait
# rien, sans la moindre erreur — la définition d'un réglage qui ment.

_ANIMATE = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
            / "animate.min.css")


def test_chaque_animation_annoncee_existe_vraiment_dans_animate_css():
    from bot.core.overlay_layout import ANIM_AUCUNE, ANIM_DEFAUT, ANIMATIONS
    css = _ANIMATE.read_text(encoding="utf-8")
    for menu in ANIMATIONS.values():
        for noms in menu.values():
            for nom in noms:
                if nom in (ANIM_DEFAUT, ANIM_AUCUNE):
                    continue        # les deux options maison
                assert f"animate__{nom}" in css, f"classe absente : {nom}"


def test_le_catalogue_ne_laisse_aucune_animation_de_cote():
    """Les quatre-vingt-dix-sept animations d'animate.css sont TOUTES joignables
    depuis l'un des trois menus. Une oubliée serait invisible à jamais : rien
    dans le panneau ne dirait qu'elle existe."""
    import re as _re
    from bot.core.overlay_layout import (
        ANIMS_ENTREE, ANIMS_INSISTANCE, ANIMS_SORTIE, ANIM_AUCUNE, ANIM_DEFAUT)
    css = _ANIMATE.read_text(encoding="utf-8")
    # Les modificateurs d'animate.css ne sont pas des animations : ils règlent
    # la durée ou la répétition d'une autre.
    modificateurs = {"animated", "delay", "repeat", "infinite",
                     "slow", "slower", "fast", "faster"}
    dans_le_css = {n for n in _re.findall(r"animate__([a-zA-Z]+)", css)
                   if n not in modificateurs and not n.startswith("delay")
                   and not n.startswith("repeat")}
    offertes = (ANIMS_ENTREE | ANIMS_SORTIE | ANIMS_INSISTANCE) \
        - {ANIM_DEFAUT, ANIM_AUCUNE}
    assert dans_le_css - offertes == set(), (
        "des animations d'animate.css ne sont dans aucun menu")


def test_une_sortie_ne_peut_pas_etre_choisie_en_entree():
    """`fadeOut` en entrée ferait disparaître le widget au moment où il
    apparaît. Les deux menus ne se recouvrent que sur les options maison."""
    from bot.core.overlay_layout import (
        ANIM_AUCUNE, ANIM_DEFAUT, ANIMS_ENTREE, ANIMS_SORTIE)
    assert ANIMS_ENTREE & ANIMS_SORTIE == {ANIM_DEFAUT, ANIM_AUCUNE}


def test_le_glitch_est_le_defaut_des_deux_menus_de_passage():
    """C'est la rafale d'aujourd'hui. La garder en tête de menu est ce qui fait
    que personne ne voit son overlay changer."""
    from bot.core.overlay_layout import ANIMATIONS, ANIM_DEFAUT
    assert ANIMATIONS["entree"]["Maison"][0] == ANIM_DEFAUT
    assert ANIMATIONS["sortie"]["Maison"][0] == ANIM_DEFAUT
    # L'insistance n'a pas de glitch : elle se rejoue en boucle, et la rafale
    # est un événement ponctuel.
    assert ANIM_DEFAUT not in ANIMATIONS["insistance"]["Maison"]
