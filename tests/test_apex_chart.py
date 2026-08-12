# tests/test_apex_chart.py
"""Le rendu de la progression en image.

Ce qu'on vérifie ici n'est pas l'esthétique : c'est qu'on ne DESSINE pas ce
qu'on n'a pas mesuré.
"""
from datetime import datetime, timedelta

import pytest

from bot.core.apex.chart import _gains_par_jour, render
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
#
# Le cumul lui-même (marches, chutes, bonds de tracker, trous coupés) est
# vérifié dans `test_apex_serie.py`, sans matplotlib. Ici on ne teste que ce que
# le DESSIN en fait.


def _textes_traces(points, titre="titre"):
    """Rend tout ce que le rendu écrit sur les axes : annotations et graduations."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ecrits: list[str] = []
    vrai_text, vrai_labels = plt.Axes.text, plt.Axes.set_xticklabels

    def _espion_text(self, x, y, s, *a, **kw):
        ecrits.append(str(s))
        return vrai_text(self, x, y, s, *a, **kw)

    def _espion_labels(self, labels, *a, **kw):
        ecrits.extend(str(v) for v in labels)
        return vrai_labels(self, labels, *a, **kw)

    plt.Axes.text, plt.Axes.set_xticklabels = _espion_text, _espion_labels
    try:
        render(points, "kills", titre)
    finally:
        plt.Axes.text, plt.Axes.set_xticklabels = vrai_text, vrai_labels
    return ecrits


def test_un_long_vide_est_annonce_par_sa_duree():
    """La bande comprimée doit dire ce qu'elle remplace, sinon l'image ment sur
    le temps écoulé entre les deux blocs."""
    points = [(T0 + i * MINUTE, 100 + i) for i in range(10)]
    points += [(T0 + 9 * 3600 + i * MINUTE, 200 + i) for i in range(10)]
    assert "⋯ 9 h" in _textes_traces(points)


def test_les_heures_restent_lisibles_de_part_et_d_autre_du_vide():
    """Comprimer le vide ne doit pas décrocher l'axe du temps réel : les deux
    blocs restent datés, à 20 h et à 5 h du matin."""
    points = [(T0 + i * MINUTE, 100 + i) for i in range(20)]
    points += [(T0 + 9 * 3600 + i * MINUTE, 300 + i) for i in range(20)]
    ecrits = _textes_traces(points)
    assert any(t.startswith("20h") for t in ecrits), ecrits
    assert any(t.startswith("05h") for t in ecrits), ecrits


def test_la_cumulative_est_tracee_en_marches():
    """Apex ne met ses compteurs à jour qu'en fin de partie : les kills
    arrivent par paliers. Une diagonale entre deux relevés dessinerait une
    montée régulière qui n'a pas eu lieu."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tracés = []
    vrai_plot = plt.Axes.plot

    def _espion(self, *a, **kw):
        tracés.append(kw.get("drawstyle"))
        return vrai_plot(self, *a, **kw)

    plt.Axes.plot = _espion
    try:
        render([(T0, 100), (T0 + 8 * MINUTE, 113)], "kills", "titre")
    finally:
        plt.Axes.plot = vrai_plot
    assert "steps-post" in tracés


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
