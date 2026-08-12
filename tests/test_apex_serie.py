# tests/test_apex_serie.py
"""La série d'une cumulative : marches, trous coupés, trous comprimés.

Ce qu'on vérifie ici n'est pas l'esthétique, c'est qu'on ne DESSINE pas ce
qu'on n'a pas mesuré — et qu'on ne consacre pas la largeur de l'image à du
vide. Le 2026-08-12, « la courbe de ce stream » rendait une image dont les
trois quarts étaient une nuit sans une seule partie.

Aucun de ces tests n'importe matplotlib : c'est tout l'intérêt d'avoir sorti la
construction du dessin.
"""
from datetime import datetime

import pytest

from bot.core.apex.history import PARIS
from bot.core.apex.serie import construire

MINUTE = 60.0
HEURE = 3600.0
T0 = datetime(2026, 8, 11, 20, 0, tzinfo=PARIS).timestamp()


def _mesures(depuis: float, combien: int, *, pas: float = MINUTE, valeur: int = 100):
    """Une suite de relevés réguliers, un kill de plus à chaque fois."""
    return [(depuis + i * pas, valeur + i) for i in range(combien)]


# ── L'abscisse ───────────────────────────────────────────────────────────────

def test_sans_trou_l_abscisse_suit_le_temps_reel():
    """Rien à comprimer : une minute de jeu occupe une minute d'image."""
    serie = construire(_mesures(T0, 10))
    assert serie.xs[-1] - serie.xs[0] == pytest.approx(9 * MINUTE)


def test_un_trou_de_neuf_heures_ne_mange_plus_la_largeur():
    """Le défaut du 2026-08-12 : deux blocs de jeu séparés par une nuit, et
    l'image consacrait les trois quarts de sa largeur à la nuit."""
    points = _mesures(T0, 10) + _mesures(T0 + 9 * HEURE, 10, valeur=200)
    serie = construire(points)

    largeur = serie.xs[-1] - serie.xs[0]
    joue = 2 * 9 * MINUTE                      # les deux blocs, 9 minutes chacun
    assert len(serie.trous) == 1
    assert largeur < joue * 2, (
        f"largeur totale {largeur:.0f} s pour {joue:.0f} s de jeu : le vide "
        "occupe encore l'essentiel de l'image"
    )


# Les intervalles entre relevés, tels qu'enregistrés en base pour le compte
# d'Azraël sur les vingt-quatre heures du 2026-08-12. Recopiés plutôt
# qu'inventés : une approximation régulière ne reproduit ni les libellés
# empilés ni les heures qui se chevauchent, qui viennent tous deux de
# l'irrégularité. 3,7 h mesurées pour 13,5 h de vide — l'ordinaire d'un compte
# qu'on ne sonde que lorsqu'on le consulte.
ECARTS_REELS = [
    819, 31, 656, 248, 441, 1172, 1210, 751, 1618, 1807, 527, 1023, 1959,
    1024, 1954, 434, 33166, 280, 496, 901, 528, 540, 1682, 1214, 1422, 279,
    1255, 651, 1327, 821, 900, 713,
]


# L'instant du premier de ces relevés. Il compte autant que les intervalles :
# les graduations se calent sur des heures RONDES, donc c'est l'alignement de
# cette grille sur les segments qui fait — ou non — se chevaucher deux heures.
# Un T0 inventé à 20h00 pile évitait le défaut par chance.
T_REEL = datetime(2026, 8, 11, 20, 41, 43, 718543, tzinfo=PARIS).timestamp()


def _journee_reelle():
    """Les relevés de prod du 2026-08-12, à leurs vrais espacements."""
    points, t, v = [(T_REEL, 100)], T_REEL, 100
    for ecart in ECARTS_REELS:
        t += ecart
        v += 4 if ecart < 1200 else 0        # les kills tombent pendant le jeu
        points.append((t, v))
    return points


def test_seuls_les_vides_qui_pesent_sont_nommes():
    """Constaté en prod le 2026-08-12 : onze bandes annotées, donc onze libellés
    empilés en bouillie illisible sur le haut de l'image.

    Nommer une pause de vingt minutes coûte plus de lisibilité qu'elle n'en
    apporte ; la nuit de neuf heures, elle, doit se lire.
    """
    serie = construire(_journee_reelle())
    nommes = [t for t in serie.trous if t.notable]

    assert len(nommes) <= 2, (
        f"{len(nommes)} libellés sur l'image : ils se chevauchent"
    )
    assert nommes and max(t.duree for t in nommes) > 8 * HEURE, (
        "la nuit de neuf heures doit être nommée : c'est le seul vide dont la "
        "durée change la lecture de la courbe"
    )


def test_les_bandes_ne_reprennent_pas_la_largeur_qu_on_leur_retire():
    """Onze bandes à 4 % chacune, c'est un tiers de l'image rendu au vide."""
    serie = construire(_journee_reelle())
    largeur = serie.xs[-1] - serie.xs[0]
    bandes = sum(t.x_fin - t.x_debut for t in serie.trous)
    assert bandes <= 0.2 * largeur, (
        f"les bandes occupent {bandes / largeur:.0%} de l'axe"
    )


def test_un_trou_court_n_est_pas_comprime():
    """Dix minutes entre deux parties, c'est du jeu qui respire, pas un vide."""
    points = _mesures(T0, 5) + _mesures(T0 + 4 * MINUTE + 10 * MINUTE, 5, valeur=200)
    serie = construire(points)
    assert serie.trous == []
    assert serie.xs[-1] - serie.xs[0] == pytest.approx(18 * MINUTE)


# ── Ce que le trou raconte ───────────────────────────────────────────────────

def test_le_trait_reste_coupe_dans_le_trou():
    """On comprime le vide, on ne le comble pas : relier les deux blocs
    dessinerait une progression nocturne qui n'a pas eu lieu."""
    points = _mesures(T0, 5) + _mesures(T0 + 9 * HEURE, 5, valeur=200)
    serie = construire(points)
    assert any(y != y for y in serie.ys)       # un NaN = trait interrompu


def test_le_trou_dit_sa_duree_reelle():
    """Comprimé à l'écran, mais annoté de ce qu'il a vraiment duré."""
    points = _mesures(T0, 5) + _mesures(T0 + 9 * HEURE, 5, valeur=200)
    (trou,) = construire(points).trous
    assert trou.libelle == "⋯ 9 h"
    assert trou.duree == pytest.approx(9 * HEURE - 4 * MINUTE)


@pytest.mark.parametrize("duree,attendu", [
    (25 * MINUTE, "⋯ 25 min"),
    (90 * MINUTE, "⋯ 1 h 30"),
    (9 * HEURE, "⋯ 9 h"),
    (3 * 24 * HEURE, "⋯ 3 j"),
])
def test_la_duree_du_trou_se_lit_a_l_echelle_humaine(duree, attendu):
    points = [(T0, 100), (T0 + MINUTE, 101),
              (T0 + MINUTE + duree, 200), (T0 + 2 * MINUTE + duree, 201)]
    (trou,) = construire(points).trous
    assert trou.libelle == attendu


# ── Les heures restent lisibles ──────────────────────────────────────────────

def test_une_abscisse_se_relit_en_heure_reelle():
    """L'axe est comprimé, donc matplotlib ne sait plus dater : c'est la série
    qui doit rendre l'heure vraie d'une abscisse."""
    serie = construire(_mesures(T0, 10))
    lu = serie.instant(serie.xs[3])
    assert lu.timestamp() == pytest.approx(T0 + 3 * MINUTE, abs=1.0)


def test_aucune_graduation_ne_tombe_dans_un_trou():
    """Une heure affichée au milieu d'une bande vide daterait le néant."""
    points = _mesures(T0, 20) + _mesures(T0 + 9 * HEURE, 20, valeur=300)
    serie = construire(points)
    (trou,) = serie.trous
    for x, _ in serie.graduations():
        assert not (trou.x_debut < x < trou.x_fin), (
            f"graduation à x={x:.0f}, dans la bande comprimée "
            f"[{trou.x_debut:.0f}, {trou.x_fin:.0f}]"
        )


def test_les_graduations_encadrent_le_trou():
    """De part et d'autre : sinon un des deux blocs n'est plus daté du tout."""
    points = _mesures(T0, 20) + _mesures(T0 + 9 * HEURE, 20, valeur=300)
    serie = construire(points)
    (trou,) = serie.trous
    xs = [x for x, _ in serie.graduations()]
    assert any(x <= trou.x_debut for x in xs)
    assert any(x >= trou.x_fin for x in xs)


def test_deux_graduations_ne_se_chevauchent_pas():
    """Vu en prod le 2026-08-12 : « 21h30 » et « 22h00 » collés de part et
    d'autre d'une bande étroite, illisibles.

    Chaque segment gradue sur sa propre grille d'heures rondes ; rien n'empêche
    la dernière d'un segment de tomber juste avant la première du suivant.
    """
    serie = construire(_journee_reelle())
    graduations = serie.graduations()
    largeur = serie.xs[-1] - serie.xs[0]
    # « 21h30 » à la taille de police du graphe occupe environ 4,3 % de l'axe.
    # Deux libellés ont donc besoin de ~7 % entre leurs centres pour respirer.
    trop_proches = [
        (a.strftime("%Hh%M"), b.strftime("%Hh%M"))
        for (xa, a), (xb, b) in zip(graduations, graduations[1:])
        if (xb - xa) < 0.07 * largeur
    ]
    assert not trop_proches, f"heures qui se recouvrent : {trop_proches}"


def test_les_graduations_sont_croissantes_et_datent_juste():
    serie = construire(_mesures(T0, 40, pas=5 * MINUTE))
    graduations = serie.graduations()
    assert len(graduations) >= 2
    assert [x for x, _ in graduations] == sorted(x for x, _ in graduations)
    for x, moment in graduations:
        assert moment.timestamp() == pytest.approx(serie.instant(x).timestamp(), abs=1.0)


# ── Le cumul lui-même (repris de l'ancien `chart._cumul`) ────────────────────

def test_le_cumul_ignore_les_bonds_de_tracker():
    """Un tracker réépinglé ferait décoller la courbe d'un coup."""
    points = [(T0, 1000), (T0 + MINUTE, 1010), (T0 + 2 * MINUTE, 92_000)]
    serie = construire(points)
    assert max(y for y in serie.ys if y == y) == 10


def test_le_cumul_ignore_les_chutes():
    points = [(T0, 1000), (T0 + MINUTE, 200), (T0 + 2 * MINUTE, 215)]
    serie = construire(points)
    assert max(y for y in serie.ys if y == y) == 15


def test_sans_trou_le_trait_est_continu():
    serie = construire(_mesures(T0, 10))
    assert all(y == y for y in serie.ys)


def test_deux_releves_isoles_ne_font_pas_planter_la_serie():
    """Cas dégénéré : tout l'intervalle est un trou, il ne reste rien à mesurer."""
    serie = construire([(T0, 100), (T0 + 9 * HEURE, 200)])
    assert serie.xs and len(serie.xs) == len(serie.ys)
