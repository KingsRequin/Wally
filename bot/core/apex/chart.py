# bot/core/apex/chart.py
"""La progression d'un compteur Apex, en image.

Deux formes, choisies par la durée couverte, parce qu'une seule ne marche pas
pour les deux usages :

- **courbe cumulative** sur une soirée : on voit la progression monter au fil
  des parties, avec ses paliers d'attente ;
- **histogramme par jour** sur une semaine ou un mois : une cumulative sur
  trente jours est une diagonale illisible, alors qu'un bâton par jour dit
  d'un coup d'œil « il a joué comme un fou le 3, rien la semaine d'après ».

Un trou dans les relevés (bot arrêté, panne d'API, nuit) est TRACÉ COMME UN
TROU. Le total, lui, reste juste — un compteur cumulatif ne perd rien — mais
relier les deux points par une droite inventerait une progression régulière qui
n'a pas eu lieu.

Ce fichier ne fait plus que DESSINER : la construction de la série cumulative
(marches, trous coupés, longs vides comprimés, graduations) vit dans
`serie.py`, où elle se teste sans ouvrir un PNG. Conséquence à ne pas perdre de
vue en le relisant : sur la cumulative, **l'abscisse n'est pas une date** mais
un temps comprimé, et seul `Serie` sait la relire.

Style repris du graphe d'émotions du journal : même fond, mêmes gris.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

from loguru import logger

from bot.core.apex.history import PARIS, plafond_plausible
from bot.core.apex.serie import Serie, construire

FOND = "#1a1a1a"
GRILLE = "#333333"
TEXTE = "#aaaaaa"
TRAIT = "#e0245e"        # le rouge Apex
CLASSE = "#f5a623"       # l'ambre des rangs — se distingue du rouge sur ce fond

# En deçà, la cumulative n'a rien à raconter : on passe aux bâtons par jour.
SEUIL_HISTOGRAMME_S = 2 * 86400
# Sous deux relevés, pas de courbe : un graphe à un point est un mensonge
# graphique. Exposé parce que l'overlay doit connaître ce seuil AVANT de mettre
# une carte à l'écran — sinon elle s'affiche au nom du joueur, et l'image qui
# devait la remplir répond 404.
MIN_POINTS = 2

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


def _colorer_le_classe(ax, serie: Serie) -> None:
    """Surtrace les marches jouées en classé, et pose la légende.

    Surtracer plutôt que découper la courbe en morceaux : le trait de base reste
    d'une seule pièce, donc aucune rupture ne peut apparaître à la jointure de
    deux couleurs.

    La légende n'existe QUE si le RP a été relevé sur la fenêtre. Sans relevé,
    tout afficher en « non classé » affirmerait quelque chose qu'on ne sait pas :
    l'historique d'avant ce déploiement n'a simplement pas de RP.
    """
    if not serie.rp_connu:
        return
    runs = serie.runs_classees()
    for rang, (xs, ys) in enumerate(runs):
        ax.plot(xs, ys, color=CLASSE, linewidth=2.5, drawstyle="steps-post",
                label="classé" if rang == 0 else None)
    if not runs:
        # Aucune partie classée sur la fenêtre : la légende garde quand même ses
        # deux entrées. « Il n'a fait que du non classé » est une information,
        # et une légende à une seule ligne se lirait comme un oubli.
        ax.plot([], [], color=CLASSE, linewidth=2.5, label="classé")
    ax.legend(
        loc="upper left", fontsize=8, facecolor=FOND, edgecolor="#444444",
        labelcolor=TEXTE, framealpha=0.85,
    )


def _marquer_les_vides(ax, serie: Serie) -> None:
    """Dit ce que remplace chaque bande comprimée.

    Sans cette annotation l'image mentirait sur le temps écoulé : deux blocs de
    jeu collés l'un à l'autre se liraient comme une seule soirée.
    """
    for trou in serie.trous:
        ax.axvline(trou.x_milieu, color=TEXTE, linestyle=":", linewidth=1, alpha=0.6)
        # Le pointillé marque TOUS les vides — c'est ce qui dit « on n'a pas
        # regardé ». Le libellé, lui, ne va qu'aux vides qui pèsent : onze
        # durées empilées sur le haut de l'image ne se lisent pas.
        if not trou.notable:
            continue
        # Repère l'axe des x en données et celui des y en fraction : la hauteur
        # de la courbe n'est pas connue ici, et la coller au sommet la garde
        # lisible quel que soit le total.
        ax.text(
            trou.x_milieu, 0.97, trou.libelle,
            transform=ax.get_xaxis_transform(),
            color=TEXTE, fontsize=8, ha="center", va="top",
            bbox={"facecolor": FOND, "edgecolor": "none", "pad": 1.5},
        )


def render(
    points: list[tuple[float, int]],
    notion: str,
    titre: str,
    *,
    rp: list[tuple[float, int]] | None = None,
) -> BytesIO | None:
    """Le PNG de la progression, ou None s'il n'y a rien à tracer.

    Sous `MIN_POINTS` relevés, pas de courbe : un graphe à un point est un
    mensonge graphique. L'appelant répond alors en chiffres.

    `rp` porte les relevés de `rank_score` : les marches jouées pendant qu'il
    bougeait sont surtracées en « classé ». Sans lui, la courbe reste monochrome
    et SANS légende — l'historique d'avant qu'on relève le RP ne dit pas « ces
    parties n'étaient pas classées », il ne dit rien.

    Bloquant (import matplotlib + rendu ≈ 1 s) — à appeler dans un thread.
    """
    if len(points) < MIN_POINTS:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001 — pas de graphe ≠ pas de réponse
        logger.warning("Apex chart: matplotlib indisponible: {e!r}", e=exc)
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
        serie = construire(points, rp=rp)
        # EN MARCHES, jamais en diagonale : Apex ne met ses compteurs à jour
        # qu'en FIN DE PARTIE. Les kills arrivent donc par paliers — 13 d'un
        # bloc à 12h51 — et une interpolation linéaire dessinerait une montée
        # régulière qui n'a pas eu lieu. Constaté sur la première courbe réelle.
        ax.plot(serie.xs, serie.ys, color=TRAIT, linewidth=2, drawstyle="steps-post",
                label="non classé" if serie.rp_connu else None)
        ax.fill_between(serie.xs, serie.ys, color=TRAIT, alpha=0.15, step="post")
        _colorer_le_classe(ax, serie)
        _marquer_les_vides(ax, serie)
        # L'abscisse est comprimée : ce n'est plus une date, et le formateur de
        # matplotlib daterait le néant au milieu des bandes. C'est la série qui
        # sait quelle heure vaut quelle abscisse.
        graduations = serie.graduations()
        ax.set_xticks([x for x, _ in graduations])
        ax.set_xticklabels([moment.strftime("%Hh%M") for _, moment in graduations])
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
