"""Le bilan de fin de partie s'affiche sur le live (§12).

« Afficher le nombre de kills de la game qui vient de se terminer » et « le cumul
depuis le début du stream ». Arbitré avec l'owner : l'affichage part TOUT SEUL à
chaque fin de partie — les viewers voient le bilan sans avoir à le demander.

La règle qui gouverne tout : **on n'affiche pas ce qu'on n'a pas mesuré**. Une
partie illisible (trackers dépinglés, Mixtape) ne donne pas « 0 kill » à l'écran ;
elle ne donne rien. Un zéro inventé est un mensonge, pas une valeur par défaut —
c'est la leçon du 2026-08-13, où 39 kills sont devenus 0 en direct.
"""
from unittest.mock import MagicMock


def _narrateur(live: bool = True):
    from bot.intelligence.overlay_narrator import OverlayNarrator
    return OverlayNarrator(overlay_feed=MagicMock(), llm=MagicMock(),
                           is_live=lambda: live)


def _widget(n):
    appels = n._feed.widget.call_args_list
    return appels[-1] if appels else None


# ── ce qui s'affiche ────────────────────────────────────────────────────────

def test_le_bilan_porte_la_partie_ET_le_cumul():
    n = _narrateur()
    assert n.show_apex_kills(partie=4, total=27, parties=6) is True
    k = _widget(n).kwargs
    assert _widget(n).args[0] == "apex_kills"
    assert k["kills"] == 4
    assert k["total"] == 27
    assert k["games"] == 6


def test_une_partie_ILLISIBLE_n_affiche_RIEN():
    """Le cœur de la règle. « Illisible » et « zéro » ne s'écrivent pas pareil à
    l'écran : le premier ne s'écrit pas du tout."""
    n = _narrateur()
    assert n.show_apex_kills(partie=None, total=27, parties=6) is False
    assert _widget(n) is None


def test_une_partie_SANS_KILL_s_affiche_quand_meme():
    """Mourir sans tuer est une partie réelle et mesurée : zéro est alors une
    information, et c'est même celle que le chat commentera le plus."""
    n = _narrateur()
    assert n.show_apex_kills(partie=0, total=27, parties=6) is True
    assert _widget(n).kwargs["kills"] == 0


def test_hors_live_rien_ne_part():
    n = _narrateur(live=False)
    assert n.show_apex_kills(partie=4, total=27, parties=6) is False


def test_des_valeurs_TORDUES_ne_partent_pas_a_l_ecran():
    """Elles viennent d'une API tierce à travers deux couches : un négatif ou un
    non-nombre serait affiché tel quel devant les viewers."""
    n = _narrateur()
    assert n.show_apex_kills(partie=-3, total=27, parties=6) is False
    assert n.show_apex_kills(partie="beaucoup", total=27, parties=6) is False


# ── le câblage ──────────────────────────────────────────────────────────────

def test_l_element_est_declare_et_placable():
    from bot.core.overlay_elements import LIBELLES
    from bot.core.overlay_layout import _ORDRE_DEFAUT, ELEMENTS

    assert LIBELLES["apex_kills"]["nom"] and LIBELLES["apex_kills"]["description"]
    assert "apex_kills" in ELEMENTS
    assert "apex_kills" in _ORDRE_DEFAUT


def test_il_COHABITE():
    """Un bilan chiffré n'est pas un spectacle : il s'affiche pendant que la
    partie suivante commence, sans effacer Wally."""
    from bot.core.overlay_layout import ELEMENTS
    assert ELEMENTS["apex_kills"]["solo"] is False
    assert ELEMENTS["apex_kills"]["wally_visible"] is True


def test_la_page_sait_le_dessiner():
    from pathlib import Path

    statique = Path(__file__).resolve().parents[1] / "bot" / "dashboard" / "static"
    assert '"apex_kills"' in (statique / "overlay_layout.js").read_text(encoding="utf-8")
    html = (statique / "overlay.html").read_text(encoding="utf-8")
    assert 'data-element="apex_kills"' in html
    assert "apex-kills" in html
    assert "apex_kills(" in (statique / "overlay.js").read_text(encoding="utf-8")


def test_le_bouton_d_essai_a_de_quoi_montrer():
    from bot.dashboard.routes.overlay import _ECHANTILLONS
    assert _ECHANTILLONS["apex_kills"]["total"]


# ── la sonde le déclenche toute seule ───────────────────────────────────────

def test_le_watcher_previent_a_la_fin_de_chaque_partie():
    """L'affichage part tout seul (choix de l'owner) : c'est la sonde qui voit
    la partie se terminer, personne d'autre ne regarde `in_game` à cette
    cadence."""
    import inspect

    from bot.core.apex import watcher

    source = inspect.getsource(watcher)
    assert "KillsDuLive" in source
    assert "_on_partie" in source


def test_le_bilan_est_branche_sur_l_affichage_au_demarrage():
    """Le rappel est posé à la construction du watcher, dans `main.py` : sans
    lui, tout le suivi tournerait pour rien — silencieusement."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "bot" / "main.py").read_text(encoding="utf-8")
    assert "on_partie=" in source
    assert "show_apex_kills" in source
