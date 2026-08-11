# bot/core/apex/chart.py
"""La progression d'un compteur Apex, en image.

Deux formes, choisies par la durée couverte, parce qu'une seule ne marche pas
pour les deux usages :

- **courbe cumulative** sur une soirée : on voit la progression monter au fil
  des parties, avec ses paliers d'attente ;
- **histogramme par jour** sur une semaine ou un mois : une cumulative sur
  trente jours est une diagonale illisible, alors qu'un bâton par jour dit
  d'un coup d'œil « il a joué comme un fou le 3, rien la semaine d'après ».

Un trou dans les relevés (bot arrêté, panne d'API) est TRACÉ COMME UN TROU.
Le total, lui, reste juste — un compteur cumulatif ne perd rien — mais relier
les deux points par une droite inventerait une progression régulière qui n'a
pas eu lieu.

Style repris du graphe d'émotions du journal : même fond, mêmes gris.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

from loguru import logger

from bot.core.apex.history import PARIS, plafond_plausible

FOND = "#1a1a1a"
GRILLE = "#333333"
TEXTE = "#aaaaaa"
TRAIT = "#e0245e"        # le rouge Apex

# Au-delà de ce multiple de l'écart courant entre deux relevés, on considère
# qu'on n'a pas mesuré l'intervalle et on interrompt le trait.
FACTEUR_TROU = 4.0
# En deçà, la cumulative n'a rien à raconter : on passe aux bâtons par jour.
SEUIL_HISTOGRAMME_S = 2 * 86400

_LIBELLES = {
    "kills": "kills", "wins": "victoires", "damage": "dégâts",
    "matches": "parties", "headshots": "headshots", "revives": "réanimations",
}


def libelle(notion: str) -> str:
    return _LIBELLES.get(notion, notion)


def _gains_par_jour(points: list[tuple[float, int]]) -> dict[datetime, int]:
    """Gains plausibles regroupés par jour civil (heure de Paris)."""
    par_jour: dict[datetime, int] = {}
    for (t_av, av), (t_ap, ap) in zip(points, points[1:]):
        ecart = ap - av
        if ecart <= 0 or ecart > plafond_plausible(t_ap - t_av):
            continue
        jour = datetime.fromtimestamp(t_ap, PARIS).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        par_jour[jour] = par_jour.get(jour, 0) + ecart
    return par_jour


def _cumul(points: list[tuple[float, int]]) -> tuple[list[datetime], list[float]]:
    """Série cumulative des gains, avec `None` là où la mesure manque.

    Les `None` de matplotlib interrompent le trait : c'est ce qui distingue
    « il n'a rien fait » de « on n'a pas regardé ».
    """
    ecarts = [t2 - t1 for (t1, _), (t2, _) in zip(points, points[1:])]
    median = sorted(ecarts)[len(ecarts) // 2] if ecarts else 0.0
    seuil_trou = max(median * FACTEUR_TROU, 300.0)

    dates = [datetime.fromtimestamp(points[0][0], PARIS)]
    valeurs: list[float] = [0.0]
    total = 0.0
    for (t_av, av), (t_ap, ap) in zip(points, points[1:]):
        if t_ap - t_av > seuil_trou:
            dates.append(datetime.fromtimestamp(t_av + 1, PARIS))
            valeurs.append(float("nan"))       # coupe le trait
        ecart = ap - av
        if 0 < ecart <= plafond_plausible(t_ap - t_av):
            total += ecart
        dates.append(datetime.fromtimestamp(t_ap, PARIS))
        valeurs.append(total)
    return dates, valeurs


def render(points: list[tuple[float, int]], notion: str, titre: str) -> BytesIO | None:
    """Le PNG de la progression, ou None s'il n'y a rien à tracer.

    Sous deux relevés, pas de courbe : un graphe à un point est un mensonge
    graphique. L'appelant répond alors en chiffres.

    Bloquant (import matplotlib + rendu ≈ 1 s) — à appeler dans un thread.
    """
    if len(points) < 2:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001 — pas de graphe ≠ pas de réponse
        logger.warning("Apex chart: matplotlib indisponible: {e}", e=exc)
        return None

    duree = points[-1][0] - points[0][0]
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor(FOND)
    ax.set_facecolor(FOND)

    if duree >= SEUIL_HISTOGRAMME_S:
        par_jour = _gains_par_jour(points)
        if not par_jour:
            plt.close(fig)
            return None
        jours = sorted(par_jour)
        # Les jours SANS jeu doivent apparaître vides, pas disparaître : c'est
        # la moitié de l'information d'un mois.
        tous = []
        curseur = jours[0]
        while curseur <= jours[-1]:
            tous.append(curseur)
            curseur += timedelta(days=1)
        # `date2num` explicite : matplotlib convertit lui-même à l'exécution,
        # mais ses annotations n'acceptent pas `list[datetime]` — autant faire
        # la conversion nous-mêmes plutôt que de museler le vérificateur.
        ax.bar(mdates.date2num(tous), [par_jour.get(j, 0) for j in tous],
               color=TRAIT, width=0.8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m", tz=PARIS))
        ax.set_ylabel(f"{libelle(notion)} par jour", color=TEXTE, fontsize=10)
    else:
        dates, valeurs = _cumul(points)
        xs = mdates.date2num(dates)
        ax.plot(xs, valeurs, color=TRAIT, linewidth=2)
        ax.fill_between(xs, valeurs, color=TRAIT, alpha=0.15)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh%M", tz=PARIS))
        ax.set_ylabel(f"{libelle(notion)} cumulés", color=TEXTE, fontsize=10)

    ax.set_title(titre, color="#ffffff", fontsize=12)
    ax.tick_params(colors=TEXTE)
    ax.grid(True, color=GRILLE, linewidth=0.5, alpha=0.5)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=FOND, dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf
