"""Un widget à média annonce la taille qu'il occupe vraiment.

Un widget de TEXTE se dimensionne par son contenu : sa taille ne peut pas se
connaître à l'avance, et la table n'en donne qu'un ordre de grandeur. Un widget
à MÉDIA, lui, affiche une image de dimensions arbitraires — le dossier de memes
va de 260 à 2100 px de côté, 30 % en portrait. Laisser le cadre épouser le média
donnait un encombrement qui changeait à chaque rotation, donc aucun repère juste
dans le panneau de mise en scène : on plaçait sur un rectangle que le rendu
n'atteignait jamais.

Ces widgets ont donc une boîte IMPOSÉE. Ce fichier vérifie la seule propriété
qui la rend fiable : **le chiffre n'existe qu'à un endroit**.

C'est le défaut qui était en place, et il ne se voyait pas à la lecture : le
panneau annonçait `meme: [720, 540]` pendant que `overlay.html` bornait à
`380 × 260`. Deux chiffres écrits à deux endroits, jamais confrontés — le
rectangle qu'on manipulait faisait trois fois et demie la surface du meme qui
s'affichait. Le rotateur avait la même maladie sous une autre forme : la table
disait 720 × 540 et le CSS `686px` (la même valeur moins le passe-partout),
recopiée à la main.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
_HTML = (_STATIC / "overlay.html").read_text(encoding="utf-8")
_JS = (_STATIC / "overlay.js").read_text(encoding="utf-8")

# Les widgets dont la boîte est imposée : la clé de la table, le sélecteur CSS
# du cadre, et le préfixe des variables qui portent la taille.
MEDIA = [("rotator", ".rotateur", "--rotateur-zone"),
         ("meme", ".meme", "--meme-zone")]

_SANS_NODE = subprocess.run(["which", "node"], capture_output=True).returncode != 0
pytestmark = pytest.mark.skipif(_SANS_NODE, reason="node absent")


def _tailles() -> dict:
    """La table, lue depuis le module lui-même — pas recopiée ici."""
    script = (
        "global.window = global;\n"
        f"require({json.dumps(str(_STATIC / 'overlay_layout.js'))});\n"
        "console.log(JSON.stringify(window.WallyLayout.TAILLES));"
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _bloc(selecteur: str) -> str:
    """Le corps d'une règle CSS de `overlay.html`."""
    m = re.search(re.escape(selecteur) + r"\s*\{(.*?)\}", _HTML, re.S)
    assert m, f"règle {selecteur} introuvable"
    return m.group(1)


def test_les_memes_ont_une_boite_carree():
    """Carrée parce que les memes le sont : rapport médian 1,07 sur les 121 du
    dossier, 30 % en portrait. Une boîte paysage aurait rogné un tiers d'entre
    eux, une boîte portrait les deux autres tiers."""
    t = _tailles()
    for cle in ("meme", "rotator"):
        assert t[cle][0] == t[cle][1], f"{cle} devrait être carré, vaut {t[cle]}"


def test_le_cadre_impose_sa_taille_au_lieu_de_suivre_le_media():
    """Sans `width`/`height` sur le cadre, il reprend la taille de l'image et
    l'encombrement redevient imprévisible — le repère avec."""
    for _, selecteur, prefixe in MEDIA:
        corps = _bloc(selecteur)
        for axe, var in (("width", f"{prefixe}-l"), ("height", f"{prefixe}-h")):
            assert re.search(rf"\b{axe}\s*:\s*var\(\s*{re.escape(var)}", corps), (
                f"{selecteur} doit imposer sa {axe} depuis {var}")
        # Sans `border-box`, le passe-partout et la bordure s'AJOUTENT à la
        # boîte : le rendu ferait 34 px de plus que le repère, sur chaque axe.
        assert "box-sizing: border-box" in corps, (
            f"{selecteur} doit compter le passe-partout dans sa boîte")


def test_le_repli_du_css_ne_ment_pas_sur_la_table():
    """`var(--x, 400px)` : le repli sert quand le JS n'a pas encore posé la
    variable. S'il ne vaut pas ce que dit la table, la page s'affiche une frame
    à une taille que le panneau n'annonce nulle part — et le jour où la table
    change sans lui, il ment pour de bon."""
    t = _tailles()
    for cle, selecteur, prefixe in MEDIA:
        corps = _bloc(selecteur)
        for i, (axe, var) in enumerate((("width", f"{prefixe}-l"),
                                        ("height", f"{prefixe}-h"))):
            m = re.search(rf"\b{axe}\s*:\s*var\(\s*{re.escape(var)}\s*,\s*(\d+)px",
                          corps)
            assert m, f"{selecteur} : repli manquant sur {axe}"
            assert int(m.group(1)) == t[cle][i], (
                f"{selecteur} {axe} : repli {m.group(1)}px, table {t[cle][i]}px")


def test_aucune_dimension_du_media_nest_ecrite_en_dur():
    """LA propriété qui compte. `max-width: 380px` sur `.meme img` est
    exactement ce qui avait divergé de la table : un chiffre plausible, écrit
    loin de l'autre, que personne ne rapproche jamais."""
    for _, selecteur, _ in MEDIA:
        for cible in (f"{selecteur} img", f"{selecteur} img, {selecteur} video"):
            m = re.search(re.escape(cible) + r"\s*\{(.*?)\}", _HTML, re.S)
            if not m:
                continue
            en_dur = re.findall(r"max-(?:width|height)\s*:\s*(\d+)px", m.group(1))
            assert not en_dur, (
                f"{cible} borne le média à {en_dur} px en dur — la boîte doit "
                f"suffire (`100%`), sinon deux chiffres décideront de la même "
                f"chose")


def test_le_passe_partout_de_python_est_celui_du_css():
    """Le calcul serveur ajoute le passe-partout à l'enveloppe du média pour
    obtenir la boîte. S'il ne vaut pas ce que le CSS applique, la boîte annoncée
    et la boîte rendue diffèrent d'autant — le défaut d'origine, en plus discret.

    Le CSS l'exprime en `padding` + `border`, des deux côtés ; Python en un seul
    nombre par widget. Les deux sont confrontés ici parce que personne ne les
    rapprocherait jamais autrement.
    """
    from bot.core.overlay_layout import PASSE_PARTOUT_MEDIA

    for cle, selecteur, _ in MEDIA:
        corps = _bloc(selecteur)
        pad = re.search(r"\bpadding\s*:\s*(\d+)px", corps)
        assert pad, f"{selecteur} : padding introuvable"
        bord = re.search(r"\bborder\s*:\s*(\d+)px", corps)
        # `border` peut être absent (aucune bordure) : il vaut alors 0.
        epaisseur = int(bord.group(1)) if bord else 0
        attendu = 2 * (int(pad.group(1)) + epaisseur)
        assert PASSE_PARTOUT_MEDIA[cle] == attendu, (
            f"{cle} : Python dit {PASSE_PARTOUT_MEDIA[cle]} px de passe-partout, "
            f"le CSS en applique {attendu} ({pad.group(1)} de padding + "
            f"{epaisseur} de bordure, des deux côtés)")


def test_le_repli_du_js_ne_depasse_pas_la_boite_acceptee():
    """La table du JS sert de repli avant que la mesure du serveur n'arrive. Un
    repli plus grand que ce qu'on accepte d'afficher ferait sauter la boîte de
    sa taille à une autre sous les yeux, à chaque ouverture de page."""
    from bot.core.overlay_layout import BOITE_MEDIA_MAX

    t = _tailles()
    for cle, _, _ in MEDIA:
        assert max(t[cle]) <= BOITE_MEDIA_MAX, (
            f"{cle} : repli {t[cle]} au-delà de la boîte acceptée "
            f"({BOITE_MEDIA_MAX})")


def test_le_js_pose_les_variables_depuis_la_table():
    """Le maillon qui relie les deux : si le JS cessait de poser la variable, le
    CSS retomberait sur son repli et la scène ne pourrait plus rien changer."""
    for cle, _, prefixe in MEDIA:
        assert f'WallyLayout.taille("{cle}")' in _JS, (
            f"overlay.js doit lire la taille de {cle} dans la table")
        for var in (f"{prefixe}-l", f"{prefixe}-h"):
            assert f'"{var}"' in _JS, f"overlay.js doit poser {var}"
