# tests/test_apex_chart.py
"""Le rendu de la progression en image.

Ce qu'on vérifie ici n'est pas l'esthétique : c'est qu'on ne DESSINE pas ce
qu'on n'a pas mesuré.
"""
from datetime import datetime, timedelta

import pytest

from bot.core.apex.chart import _cumul, _gains_par_jour, render
from bot.core.apex.history import PARIS

MINUTE = 60.0
JOUR = 86400.0
T0 = datetime(2026, 8, 11, 20, 0, tzinfo=PARIS).timestamp()


def test_sous_deux_releves_il_n_y_a_pas_de_courbe():
    """Un graphe à un point est un mensonge graphique."""
    assert render([(T0, 100)], "kills", "titre") is None
    assert render([], "kills", "titre") is None


def test_une_soiree_donne_une_image():
    points = [(T0 + i * MINUTE, 100 + i) for i in range(20)]
    png = render(points, "kills", "Kills de la session")
    assert png is not None and png.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def test_un_mois_donne_une_image():
    points = [(T0 + i * JOUR, 100 + i * 12) for i in range(20)]
    png = render(points, "kills", "Kills du mois")
    assert png is not None and png.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


# ── Ce que la courbe raconte ─────────────────────────────────────────────────

def test_le_cumul_ignore_les_bonds_de_tracker():
    """Un tracker réépinglé ferait décoller la courbe d'un coup."""
    points = [(T0, 1000), (T0 + MINUTE, 1010), (T0 + 2 * MINUTE, 92_000)]
    _, valeurs = _cumul(points)
    assert max(v for v in valeurs if v == v) == 10


def test_le_cumul_ignore_les_chutes():
    points = [(T0, 1000), (T0 + MINUTE, 200), (T0 + 2 * MINUTE, 215)]
    _, valeurs = _cumul(points)
    assert max(v for v in valeurs if v == v) == 15


def test_un_trou_de_mesure_coupe_le_trait():
    """Bot arrêté six heures : le total reste juste, mais relier les deux points
    dessinerait une progression régulière qui n'a pas eu lieu."""
    points = [
        (T0, 100), (T0 + MINUTE, 105), (T0 + 2 * MINUTE, 110),
        (T0 + 6 * 3600, 300),                     # long trou
        (T0 + 6 * 3600 + MINUTE, 305),
    ]
    _, valeurs = _cumul(points)
    assert any(v != v for v in valeurs)           # un NaN = trait interrompu


def test_sans_trou_le_trait_est_continu():
    points = [(T0 + i * MINUTE, 100 + i) for i in range(10)]
    _, valeurs = _cumul(points)
    assert all(v == v for v in valeurs)


def test_les_gains_sont_regroupes_par_jour():
    points = [
        (T0, 100),
        (T0 + 2 * 3600, 130),                     # même soirée : +30
        (T0 + JOUR, 150),                         # lendemain : +20
    ]
    par_jour = _gains_par_jour(points)
    assert sorted(par_jour.values()) == [20, 30]


def test_un_jour_sans_jeu_reste_visible():
    """Sur un mois, les jours creux sont la moitié de l'information."""
    points = [(T0, 100), (T0 + 3 * JOUR, 160)]
    png = render(points, "kills", "titre")
    assert png is not None                        # les jours vides sont comblés


@pytest.mark.parametrize("notion,attendu", [
    ("kills", "kills"), ("wins", "victoires"), ("damage", "dégâts"),
])
def test_les_notions_sont_traduites(notion, attendu):
    from bot.core.apex.chart import libelle
    assert libelle(notion) == attendu


def test_le_decoupage_par_jour_suit_l_heure_de_paris():
    """Un live du soir ne doit pas se retrouver à cheval sur deux jours."""
    minuit_paris = datetime(2026, 8, 11, 23, 30, tzinfo=PARIS)
    points = [(minuit_paris.timestamp(), 100),
              ((minuit_paris + timedelta(minutes=20)).timestamp(), 120)]
    par_jour = _gains_par_jour(points)
    assert list(par_jour)[0].day == 11
