"""Un meme tombe jusqu'en BAS de l'écran.

« Les memes disparaissent avant d'arriver en bas. » La cause est un piège CSS
classique : dans `translateY()`, un pourcentage se rapporte à la hauteur de
L'ÉLÉMENT, jamais à celle de son conteneur. `translateY(160%)` sur une vignette
de 200 px de haut la déplaçait donc de 320 px — partie de `top: -40%` (soit
-432 px sur un écran de 1080), elle mourait à hauteur du premier tiers, en plein
vol.

La propriété à tenir, et non la ligne : **la distance de chute se mesure sur le
VIEWPORT**, pas sur le meme. Sans quoi les grandes vignettes tomberaient plus
loin que les petites — ce qui était le cas, et se voyait.

Ce test échoue sur le CSS d'avant.
"""
import re
from pathlib import Path

import pytest

_HTML = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static" / "overlay.html"


@pytest.fixture(scope="module")
def chute() -> str:
    """Le corps de `@keyframes meme-chute`."""
    src = _HTML.read_text(encoding="utf-8")
    m = re.search(r"@keyframes\s+meme-chute\s*\{(.+?)\n\s*\}\s*\n", src, re.S)
    assert m, "le keyframe de la chute a disparu"
    return m.group(1)


def test_la_chute_se_mesure_sur_le_VIEWPORT():
    """Une hauteur d'écran au moins : le flocon part au-dessus du cadre et doit
    en ressortir par le bas."""
    src = _HTML.read_text(encoding="utf-8")
    m = re.search(r"@keyframes\s+meme-chute\s*\{(.+?)\n\s*\}\s*\n", src, re.S)
    corps = m.group(1)
    arrivee = re.search(r"to\s*\{[^}]*translateY\(([^)]*)\)", corps)
    assert arrivee, corps
    distance = arrivee.group(1)
    assert "vh" in distance, (
        "la distance est exprimée en pourcentage de la vignette, donc les grands "
        f"memes tombent plus loin que les petits : {distance}")


def test_le_meme_NAIT_hors_champ_quelle_que_soit_sa_hauteur():
    """« Il faut garder le spawn hors écran en haut » (owner).

    Un `top: -40%` est une DISTANCE, pas une position relative à soi : les memes
    hauts naissaient déjà dans l'écran et on les voyait surgir en cours de
    chute. `bottom: 100%` cale le bas du meme sur le bord haut de la scène —
    hors champ pour toutes les tailles, y compris celles qu'on n'a pas encore
    dans le dossier.
    """
    src = _HTML.read_text(encoding="utf-8")
    bloc = re.search(r"\.meme-storm\s+\.flocon\s*\{([^}]*)\}", src)
    assert bloc, "le style du flocon a disparu"
    assert re.search(r"bottom:\s*100%", bloc.group(1)), bloc.group(1)
    assert not re.search(r"top:\s*-?\d", bloc.group(1)), (
        "un point de départ en distance fixe laisse les grands memes naître à "
        f"l'écran : {bloc.group(1)}")


def test_la_chute_traverse_TOUTE_la_scene():
    """Le meme part perché au-dessus du bord haut : il lui faut la hauteur de
    l'écran (100vh) pour le traverser, plus la sienne (100%) pour en ressortir
    entièrement avant d'être retiré."""
    src = _HTML.read_text(encoding="utf-8")
    corps = re.search(r"@keyframes\s+meme-chute\s*\{(.+?)\n\s*\}\s*\n", src, re.S).group(1)
    arrivee = re.search(r"to\s*\{[^}]*translateY\(([^)]*\)?[^)]*)\)", corps)
    assert arrivee, corps
    distance = arrivee.group(1)
    vh = re.search(r"(\d+(?:\.\d+)?)vh", distance)
    assert vh and float(vh.group(1)) >= 100, distance
    assert "100%" in distance, (
        f"sans sa propre hauteur, le meme est retiré alors qu'il dépasse "
        f"encore du bord bas : {distance}")


def test_la_boite_de_l_avalanche_occupe_tout_l_ecran():
    """`top: -40%` et la chute se comptent en proportion de cette boîte : si
    elle rétrécit, les deux suivent — et le calcul ci-dessus avec."""
    src = _HTML.read_text(encoding="utf-8")
    bloc = re.search(r"\.meme-storm\s*\{([^}]*)\}", src)
    assert bloc, "la boîte de l'avalanche a disparu"
    assert "100vh" in bloc.group(1) and "100vw" in bloc.group(1), bloc.group(1)
