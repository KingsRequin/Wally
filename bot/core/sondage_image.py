"""La carte du sondage Discord, dessinée à la manière de l'overlay.

Discord ne sait pas afficher le widget `.poll` de l'overlay : il affiche une
image. On redessine donc la même carte avec Pillow — verre sombre, question en
Fredoka, sablier, barres arrondies en dégradé, gagnant en vert à la clôture.
Les couleurs sont celles de `:root` dans `overlay.html`, recopiées ici parce
qu'un PNG ne lit pas de CSS ; toute retouche de charte se fait AUX DEUX
endroits.

Pas d'emoji DANS l'image : les options s'y numérotent « 1. », comme sur
l'overlay. Les emojis `1️⃣` vivent en réactions sous le message, là où on clique.

⚠️ Fredoka n'était livrée qu'en `.woff2` (`bot/dashboard/static/fonts/`), un
format que Pillow ne sait pas ouvrir — le `.ttf` variable committé à côté est ce
qui donne au sondage le visage de l'overlay. S'il manque, on retombe sur DejaVu
plutôt que de ne rien rendre : une carte moins jolie vaut mieux qu'un sondage
sans image.

Le dessin est CPU-bound (~30 ms) : les appelants le passent en
`asyncio.to_thread`, la boucle porte le vocal.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from bot.core.sondage import Sondage

# `load_default()` ne rend pas une `FreeTypeFont` : le repli ultime a son propre
# type, et tout ce qui reçoit une police doit accepter les deux.
Police = ImageFont.ImageFont | ImageFont.FreeTypeFont

POLICE = (Path(__file__).resolve().parents[1]
          / "dashboard" / "static" / "fonts" / "fredoka.ttf")
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

# Charte de l'overlay (`overlay.html`, `:root`).
# ⚠️ Les couleurs semi-transparentes de la charte sont PRÉ-MÉLANGÉES sur le fond
# de la carte : `ImageDraw` REMPLACE le pixel, il ne compose pas. Un blanc à
# 10 % dessiné tel quel perce la carte au lieu de l'éclaircir — et l'on voit le
# thème de Discord au travers de la piste des barres.
_FOND = (18, 18, 22, 255)          # --glass, opaque : rien ne passe derrière ici
_LIGNE = (50, 50, 54, 255)         # --line (blanc 14 %) mélangé sur le fond
_TEXTE = (255, 255, 255, 255)
_DIM = (160, 160, 162, 255)        # --dim
_PISTE = (42, 42, 45, 255)         # blanc 10 % mélangé sur le fond
_WHO = (183, 156, 255)             # --who
_WHO_DEEP = (157, 123, 255)        # --who-deep
_INFO = (70, 198, 255)             # --info
_WIN = (125, 255, 176)             # --win
_WIN_DEEP = (52, 209, 127)         # --win-deep

LARGEUR = 620
_MARGE = 26
_RAYON = 18
_H_QUESTION = 30                   # interligne de la question
_H_SABLIER = 5
_H_BARRE = 15
_H_LIGNE_OPT = 25                  # la ligne « 1. Label … 3 · 42 % »
_ECART_OPT = 14
# Ce qu'il reste d'une option perdante à la clôture : l'overlay les passe à
# `opacity: .45`. Un PNG n'ayant pas de couche d'opacité par élément, on mélange
# vers le fond — même résultat à l'œil.
_ESTOMPE = 0.45


@lru_cache(maxsize=32)
def _police(taille: int, graisse: str) -> Police:
    """Fredoka à la graisse demandée, DejaVu en repli, jamais d'exception."""
    try:
        police = ImageFont.truetype(str(POLICE), taille)
        police.set_variation_by_name(graisse)
        return police
    except (OSError, ValueError) as exc:
        logger.warning("Sondage: Fredoka indisponible ({e!r}), repli DejaVu",
                       e=exc)
    try:
        return ImageFont.truetype(str(_DEJAVU), taille)
    except OSError as exc:
        logger.warning("Sondage: DejaVu indisponible ({e!r})", e=exc)
        return ImageFont.load_default(size=taille)


def _melange(couleur: tuple[int, int, int], part: float) -> tuple[int, int, int]:
    """La couleur estompée vers le fond de la carte."""
    return tuple(int(c * part + _FOND[i] * (1 - part))  # type: ignore[return-value]
                 for i, c in enumerate(couleur))


def _couper(texte: str, police: Police, largeur: int) -> list[str]:
    """Découpe en lignes qui tiennent dans `largeur`, mot à mot."""
    lignes: list[str] = []
    courante = ""
    for mot in (texte or "").split():
        essai = f"{courante} {mot}".strip()
        if courante and police.getlength(essai) > largeur:
            lignes.append(courante)
            courante = mot
        else:
            courante = essai
    if courante:
        lignes.append(courante)
    return lignes or [""]


def _barre(canevas: Image.Image, boite: tuple[int, int, int, int], ratio: float,
           gauche: tuple[int, int, int], droite: tuple[int, int, int]) -> None:
    """Une barre arrondie remplie d'un dégradé horizontal, comme en CSS."""
    x0, y0, x1, y1 = boite
    largeur, hauteur = x1 - x0, y1 - y0
    if largeur <= 0 or hauteur <= 0:
        return
    dessin = ImageDraw.Draw(canevas)
    rayon = hauteur // 2
    dessin.rounded_rectangle(boite, radius=rayon, fill=_PISTE)
    remplie = int(largeur * max(0.0, min(1.0, ratio)))
    if remplie < 2:
        return
    # Le dégradé tient dans la partie REMPLIE, pas dans la piste : en CSS la
    # barre est peinte sur toute sa largeur puis `scaleX(ratio)` la comprime,
    # donc on voit le dégradé entier quel que soit le score. Peint sur la
    # largeur totale puis rogné, une barre à 20 % n'en montrerait que le début.
    degrade = Image.new("RGB", (remplie, 1))
    pixels = degrade.load()
    assert pixels is not None
    for x in range(remplie):
        part = x / max(1, remplie - 1)
        pixels[x, 0] = tuple(int(g + (d - g) * part)
                             for g, d in zip(gauche, droite, strict=True))
    degrade = degrade.resize((remplie, hauteur))
    masque = Image.new("L", (remplie, hauteur), 0)
    ImageDraw.Draw(masque).rounded_rectangle(
        (0, 0, remplie - 1, hauteur - 1), radius=rayon, fill=255)
    canevas.paste(degrade, (x0, y0), masque)


def _hauteur(sondage: Sondage, lignes_question: int) -> int:
    hauteur = _MARGE + lignes_question * _H_QUESTION + 8
    if sondage.ends_at is not None:
        hauteur += _H_SABLIER + 12
    hauteur += len(sondage.options) * (_H_LIGNE_OPT + _H_BARRE + _ECART_OPT)
    return hauteur + 22 + _MARGE          # + la ligne de pied


def rendre(sondage: Sondage, *, maintenant: Optional[float] = None) -> bytes:
    """Le PNG du sondage dans son état courant."""
    police_q = _police(27, "SemiBold")
    police_pt = _police(18, "Medium")
    police_pied = _police(16, "Regular")

    interieur = LARGEUR - 2 * _MARGE
    lignes_q = _couper(sondage.question, police_q, interieur)
    hauteur = _hauteur(sondage, len(lignes_q))

    carte = Image.new("RGBA", (LARGEUR, hauteur), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(carte)
    dessin.rounded_rectangle((0, 0, LARGEUR - 1, hauteur - 1), radius=_RAYON,
                             fill=_FOND, outline=_LIGNE, width=1)

    y = _MARGE
    for ligne in lignes_q:
        dessin.text((_MARGE, y), ligne, font=police_q, fill=_TEXTE)
        y += _H_QUESTION
    y += 8

    # Sablier : il n'existe que s'il y a une échéance — un sondage sans durée
    # n'a rien à faire couler.
    reste = sondage.restant(maintenant)
    if sondage.ends_at is not None:
        part = 0.0
        if not sondage.clos and reste and sondage.duree_s:
            part = max(0.0, min(1.0, reste / sondage.duree_s))
        _barre(carte, (_MARGE, y, LARGEUR - _MARGE, y + _H_SABLIER), part,
               _WHO, _INFO)
        y += _H_SABLIER + 12

    resultat = sondage.depouiller()
    for index, option in enumerate(sondage.options):
        voix = resultat.tally[index]
        pourcent = round(100 * voix / resultat.total) if resultat.total else 0
        gagne = sondage.clos and resultat.gagnant == index
        perd = sondage.clos and not gagne
        part = _ESTOMPE if perd else 1.0

        couleur = _melange(_WIN if gagne else (255, 255, 255), part)
        police_ligne = _police(20, "SemiBold" if gagne else "Medium")
        dessin.text((_MARGE, y), f"{index + 1}. {option}", font=police_ligne,
                    fill=couleur)
        compte = f"{voix} · {pourcent} %"
        largeur_compte = police_pt.getlength(compte)
        dessin.text((LARGEUR - _MARGE - largeur_compte, y + 1), compte,
                    font=police_pt,
                    fill=_melange(_WIN if gagne else _DIM[:3], part))
        y += _H_LIGNE_OPT

        ratio = voix / resultat.total if resultat.total else 0.0
        _barre(carte, (_MARGE, y, LARGEUR - _MARGE, y + _H_BARRE), ratio,
               _melange(_WIN_DEEP if gagne else _INFO, part),
               _melange(_WIN if gagne else _WHO_DEEP, part))
        y += _H_BARRE + _ECART_OPT

    pied = f"{resultat.total} vote{'s' if resultat.total > 1 else ''}"
    if sondage.clos:
        pied += " · sondage clos"
    elif reste is not None:
        minutes, secondes = divmod(int(reste), 60)
        pied += f" · {minutes}:{secondes:02d} restantes"
    else:
        pied += " · clique un chiffre pour voter"
    dessin.text((_MARGE, y), pied, font=police_pied, fill=_DIM)

    tampon = io.BytesIO()
    carte.save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()
