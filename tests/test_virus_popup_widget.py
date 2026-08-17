"""Le spam de popups est un widget d'overlay à part entière.

Essai demandé par l'owner à côté de l'avalanche de memes : « save l'avalanche,
juste on essaie ça et je choisirai entre les deux ». Les deux coexistent donc, et
celui-ci se règle comme les autres — sans quoi il ne serait pas comparable.

Un widget se câble à HUIT endroits dans ce dépôt (déclaration, position par
défaut, ordre d'empilement, liste plaçable du panneau, taille de sa boîte,
échantillon du ▶, empreinte de version, builder). En oublier un ne casse rien de
visible : ça donne un élément qu'on ne peut pas placer, ou un cadre faux dans le
panneau. C'est ce que ce fichier surveille.
"""
from unittest.mock import MagicMock

import pytest


def _narrateur(nb_medias: int = 134, live: bool = True):
    from bot.intelligence.overlay_narrator import OverlayNarrator
    memes = MagicMock()
    memes.list_medias.return_value = [
        {"name": f"m{i}.webp", "genre": "image"} for i in range(nb_medias)
    ]
    return OverlayNarrator(
        overlay_feed=MagicMock(), llm=MagicMock(), is_live=lambda: live, memes=memes,
    )


def _widget(n):
    appels = n._feed.widget.call_args_list
    return appels[-1] if appels else None


# ── le déclenchement ────────────────────────────────────────────────────────

def test_le_spam_part_et_porte_sa_duree():
    n = _narrateur()
    assert n.show_virus_popups() is True
    appel = _widget(n)
    assert appel.args[0] == "virus_popup"
    assert appel.kwargs["seconds"] > 0


def test_la_carte_reste_le_temps_de_l_ECRAN_BLEU():
    """Le final choisi par l'owner : l'écran bleu recouvre tout, puis la carte
    se retire. Si elle part à la fin du spam, on ne le voit jamais."""
    from bot.intelligence.overlay_narrator import OverlayNarrator
    n = _narrateur()
    n.show_virus_popups()
    k = _widget(n).kwargs
    assert k["duration"] >= k["seconds"] + OverlayNarrator.VIRUS_BSOD_S


def test_un_dossier_de_memes_VIDE_ne_l_empeche_pas():
    """Contrairement à l'avalanche, ce spectacle ne dépend pas du dossier : les
    fausses alertes se suffisent. Refuser ici priverait d'un effet qui marche."""
    n = _narrateur(nb_medias=0)
    assert n.show_virus_popups() is True


def test_hors_live_rien_ne_part():
    n = _narrateur(live=False)
    assert n.show_virus_popups() is False
    assert _widget(n) is None


def test_une_duree_imposee_reste_prioritaire():
    n = _narrateur()
    n.show_virus_popups(seconds=9)
    assert _widget(n).kwargs["seconds"] == 9


# ── les huit points de câblage ──────────────────────────────────────────────

def test_l_element_est_DECLARE():
    """Sans libellé, le panneau affiche une clé technique — et l'élément est
    illisible pour qui règle la scène."""
    from bot.core.overlay_elements import LIBELLES
    assert "virus_popup" in LIBELLES
    assert LIBELLES["virus_popup"]["nom"]
    assert LIBELLES["virus_popup"]["description"]


def test_il_a_une_position_par_defaut_et_une_place_dans_l_empilement():
    from bot.core.overlay_layout import _ORDRE_DEFAUT, ELEMENTS
    assert "virus_popup" in ELEMENTS
    assert "virus_popup" in _ORDRE_DEFAUT


def test_il_couvre_le_canvas_comme_l_avalanche():
    """Il prend l'écran entier, donc il s'ancre au COIN : centrée, une carte de
    100vw partirait du milieu de l'écran et se rattraperait par un `translate` —
    l'avalanche y a perdu 77 px et deux memes par la droite."""
    from bot.core.overlay_layout import ELEMENTS
    coin = ELEMENTS["virus_popup"]
    assert (coin["x"], coin["y"]) == (0.0, 0.0)
    assert coin["anchor"] == "top-left"


def test_le_panneau_peut_le_PLACER():
    """`appliquer()` n'itère que sur sa propre liste : une clé absente est un
    widget qu'on ne peut pas régler, en silence."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
          / "overlay_layout.js").read_text(encoding="utf-8")
    assert '"virus_popup"' in js


def test_le_bouton_d_essai_lui_donne_de_quoi_MONTER_EN_REGIME():
    """Le ▶ sert à régler : trop court, on ne voit ni l'accélération ni l'écran
    bleu — exactement le défaut qu'a eu l'avalanche à cinq secondes."""
    from bot.dashboard.routes.overlay import _ECHANTILLONS
    assert _ECHANTILLONS["virus_popup"]["seconds"] >= 10


def test_son_script_compte_dans_l_empreinte_de_version():
    """Hors de `_OVERLAY_FILES`, OBS garderait son ancienne copie pour
    toujours."""
    from bot.dashboard.routes.overlay import _OVERLAY_FILES
    assert "overlay_virus.js" in _OVERLAY_FILES


def test_la_hauteur_d_une_fenetre_a_meme_est_BORNEE():
    """La position est tirée AVANT que l'image soit chargée : sa hauteur réelle
    dépend de son ratio, que personne ne connaît à ce moment-là. Sans borne, un
    meme très haut sort par le bas — mesuré dans le navigateur, quatre fenêtres
    sur soixante-six. Bornée, la fenêtre rétrécit au lieu de déborder.
    """
    import re
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
            / "overlay.html").read_text(encoding="utf-8")
    bloc = re.search(r"\.virus-popup \.vwin-meme img[^{]*\{([^}]*)\}", html, re.S)
    assert bloc, "le style de l'image d'une fenêtre à meme a disparu"
    assert re.search(r"max-height:\s*\d+vh", bloc.group(1)), bloc.group(1)


@pytest.mark.parametrize("marqueur", ["virus-popup", "virus-bsod"])
def test_la_page_porte_les_styles_du_spectacle(marqueur):
    """Les fenêtres et l'écran bleu sont du CSS : sans lui, le builder produit
    des boîtes invisibles."""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
            / "overlay.html").read_text(encoding="utf-8")
    assert marqueur in html
