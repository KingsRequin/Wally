# bot/core/apex/serie.py
"""La série d'une cumulative Apex : ce qu'on trace, avant de savoir le dessiner.

Sorti de `chart.py` pour deux raisons. La première est qu'on peut le tester sans
matplotlib, donc sans regarder un PNG pour savoir si un trou a été compté.
La seconde est que `chart.py` portait déjà les marches, les trous et le cumul en
plus du dessin, et allait recevoir la compression puis les couleurs : c'est le
genre de fichier qu'on finit par ne plus relire.

## Le vide n'a pas droit à la même largeur que le jeu

Un compteur Apex ne bouge qu'en fin de partie, et personne ne joue la nuit. Une
courbe « de ce stream » tracée sur le temps réel consacre donc les trois quarts
de sa largeur à des heures où rien ne s'est passé — constaté le 2026-08-12, où
neuf heures de sommeil occupaient l'essentiel de l'image.

Au-delà de `SEUIL_COMPRESSION_S`, l'intervalle est donc réduit à une bande
étroite, que l'appelant marque d'un pointillé et annote de sa durée réelle. **On
comprime le vide, on ne le comble pas** : le trait reste interrompu, parce que
relier les deux blocs dessinerait une progression nocturne qui n'a pas eu lieu.

Conséquence directe : l'abscisse n'est plus une date, et matplotlib ne sait plus
graduer l'axe. C'est `Serie.graduations()` qui rend les heures vraies, et
`Serie.instant()` qui relit une abscisse.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime

from bot.core.apex.history import PARIS, plafond_plausible

# Au-delà de ce multiple de l'écart courant entre deux relevés, on considère
# qu'on n'a pas mesuré l'intervalle et on interrompt le trait.
FACTEUR_TROU = 4.0
COUPURE_MIN_S = 300.0

# Plancher absolu de la compression. Vingt minutes : une partie d'Apex dure une
# quinzaine de minutes, donc en deçà on regarde du jeu qui respire — entre deux
# parties, un chargement, une pause — et l'écraser mentirait sur le rythme.
SEUIL_COMPRESSION_S = 1200.0

# Largeur d'une bande, en fraction du temps réellement mesuré. Assez large pour
# qu'on la voie, assez étroite pour qu'une nuit ne reprenne pas la place qu'on
# vient de lui retirer.
FRACTION_BANDE = 0.04
BANDE_MIN_S = 60.0

# Mais les bandes ont aussi un budget COMMUN. En prod le 2026-08-12, un compte
# sondé par intermittence donnait onze trous sur une journée : à 4 % chacune,
# les bandes reprenaient 26 % de l'image — un quart de la largeur rendu au vide
# qu'on venait d'en chasser. Au-delà de deux ou trois trous, chacune rétrécit.
FRACTION_BANDES_TOTAL = 0.15

# Un vide ne se NOMME que s'il pèse au moins cette part de la période couverte.
# Le même relevé de prod affichait onze libellés empilés en bouillie illisible :
# savoir qu'une pause a duré vingt minutes ne change rien à la lecture de la
# courbe, savoir qu'une nuit de neuf heures s'est écoulée change tout.
PART_ANNOTATION = 0.10

# Écart minimal entre deux heures affichées, en fraction de la largeur. Un
# « 21h30 » à la taille de police du graphe occupe environ 4,3 % de l'axe : sans
# cette marge, deux blocs séparés d'une bande étroite écrivent leurs heures
# l'une sur l'autre.
ESPACEMENT_MIN = 0.07

# Pas de graduation possibles, du plus fin au plus grossier. On prend le plus
# proche de l'espacement idéal plutôt qu'un pas calculé : « toutes les 17 min »
# ne se lit pas.
_PAS = (60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)


def _arrondi_lisible(secondes: float) -> tuple[int, int, int]:
    """Rend (jours, heures, minutes), arrondis à la précision qui sert.

    Plus le trou est long, plus la minute près est du bruit : personne ne lit
    « 8 h 56 » de sommeil, on lit « 9 h ». Trois paliers suffisent.
    """
    if secondes >= 86400:
        return round(secondes / 86400), 0, 0
    if secondes >= 4 * 3600:
        return 0, round(secondes / 3600), 0
    if secondes >= 3600:
        quarts = round(secondes / 900)
        return 0, quarts // 4, (quarts % 4) * 15
    return 0, 0, round(secondes / 60)


@dataclass(frozen=True)
class Trou:
    """Un intervalle sans relevé, comprimé à l'écran mais dit en entier."""

    debut: float        # instants RÉELS, pour l'annotation
    fin: float
    x_debut: float      # abscisses COMPRIMÉES, pour le dessin
    x_fin: float
    notable: bool       # pèse assez pour mériter son libellé à l'écran

    @property
    def duree(self) -> float:
        return self.fin - self.debut

    @property
    def x_milieu(self) -> float:
        return (self.x_debut + self.x_fin) / 2.0

    @property
    def libelle(self) -> str:
        jours, heures, minutes = _arrondi_lisible(self.duree)
        if jours:
            return f"⋯ {jours} j"
        if heures:
            return f"⋯ {heures} h {minutes}" if minutes else f"⋯ {heures} h"
        return f"⋯ {minutes} min"


@dataclass(frozen=True)
class Segment:
    """Une plage effectivement mesurée, tracée à l'échelle du temps réel."""

    debut: float
    fin: float
    x_debut: float

    @property
    def duree(self) -> float:
        return self.fin - self.debut

    @property
    def x_fin(self) -> float:
        return self.x_debut + self.duree


@dataclass
class Serie:
    """Ce qu'il y a à tracer : des abscisses comprimées et de quoi les dater."""

    xs: list[float]
    ys: list[float]
    trous: list[Trou]
    segments: list[Segment]
    # `classes[i]` décrit la marche tracée de `xs[i]` à `xs[i+1]` : vrai si le
    # RP a bougé pendant cet intervalle, donc si la partie était classée.
    classes: list[bool]
    # Faux quand la fenêtre ne contient AUCUN relevé de RP. La courbe reste
    # alors monochrome et sans légende : l'historique d'avant qu'on relève le RP
    # ne dit pas « ces parties n'étaient pas classées », il ne dit rien.
    rp_connu: bool

    def runs_classees(self) -> list[tuple[list[float], list[float]]]:
        """Les suites de marches classées, prêtes à être surtracées.

        Deux marches classées d'affilée forment un seul trait : les tracer
        séparément laisserait une rupture visible entre elles.
        """
        runs: list[tuple[list[float], list[float]]] = []
        debut: int | None = None
        for i, classe in enumerate(self.classes):
            if classe and debut is None:
                debut = i
            elif not classe and debut is not None:
                runs.append((self.xs[debut : i + 1], self.ys[debut : i + 1]))
                debut = None
        if debut is not None:
            runs.append((self.xs[debut:], self.ys[debut:]))
        return runs

    @property
    def duree_utile(self) -> float:
        """Le temps réellement mesuré, trous exclus."""
        return sum(s.duree for s in self.segments)

    def instant(self, x: float) -> datetime:
        """L'heure vraie d'une abscisse comprimée.

        Une abscisse tombée dans une bande est ramenée au bord le plus proche :
        il n'existe aucun instant à lui associer, et rendre le milieu du trou
        daterait le néant.
        """
        for segment in self.segments:
            if x <= segment.x_fin:
                borne = min(max(x, segment.x_debut), segment.x_fin)
                return datetime.fromtimestamp(
                    segment.debut + (borne - segment.x_debut), PARIS
                )
        dernier = self.segments[-1]
        return datetime.fromtimestamp(dernier.fin, PARIS)

    def graduations(self, combien: int = 6) -> list[tuple[float, datetime]]:
        """Les heures à afficher, à leur abscisse comprimée.

        Calées sur des instants ronds de l'heure de Paris et jamais placées dans
        une bande : une heure affichée au milieu d'un vide daterait le néant.
        """
        if not self.segments:
            return []
        utile = self.duree_utile
        if utile <= 0:
            return [
                (s.x_debut, datetime.fromtimestamp(s.debut, PARIS))
                for s in self.segments[:1]
            ]
        ideal = utile / max(1, combien)
        pas = min(_PAS, key=lambda p: abs(p - ideal))

        brutes: list[tuple[float, datetime, bool]] = []
        for segment in self.segments:
            minuit = (
                datetime.fromtimestamp(segment.debut, PARIS)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            k = math.ceil((segment.debut - minuit) / pas)
            instant = minuit + k * pas
            ouvre_le_bloc = True
            while instant <= segment.fin:
                brutes.append(
                    (
                        segment.x_debut + (instant - segment.debut),
                        datetime.fromtimestamp(instant, PARIS),
                        ouvre_le_bloc,
                    )
                )
                ouvre_le_bloc = False
                instant += pas
        return self._espacer(brutes)

    def _espacer(
        self, brutes: list[tuple[float, datetime, bool]]
    ) -> list[tuple[float, datetime]]:
        """Écarte les heures qui se recouvriraient.

        Chaque bloc gradue sur sa propre grille d'heures rondes : rien n'empêche
        la dernière d'un bloc de tomber juste avant la première du suivant, de
        part et d'autre d'une bande étroite. Vu en prod le 2026-08-12, « 21h30 »
        et « 22h00 » collés l'un à l'autre.
        """
        largeur = (self.xs[-1] - self.xs[0]) if self.xs else 0.0
        minimum = ESPACEMENT_MIN * largeur
        gardees: list[tuple[float, datetime, bool]] = []
        for tick in brutes:
            if gardees and tick[0] - gardees[-1][0] < minimum:
                # Entre deux heures trop proches, on garde celle qui OUVRE un
                # bloc : sans elle, un bloc entier resterait sans date.
                assez_loin = len(gardees) < 2 or tick[0] - gardees[-2][0] >= minimum
                if tick[2] and not gardees[-1][2] and assez_loin:
                    gardees[-1] = tick
                continue
            gardees.append(tick)
        return [(x, moment) for x, moment, _ in gardees]


def _espacer_les_libelles(trous: list[Trou], largeur: float) -> list[Trou]:
    """Retire leur libellé aux trous dont l'annotation en recouvrirait une autre.

    Même contrainte que pour les heures, oubliée sur les durées : « ⋯ 28 m » se
    faisait manger par « ⋯ 24 min » sur la session du 2026-08-12. Les plus longs
    gardent la parole — c'est leur durée qui change la lecture de la courbe.
    """
    if largeur <= 0:
        return trous
    minimum = ESPACEMENT_MIN * largeur
    gardes: list[float] = []
    # Par RANG, jamais par valeur : `Trou` est comparé champ à champ, et
    # `list.index()` rendrait le premier trou ÉGAL plutôt que celui qu'on tient.
    for rang in sorted(range(len(trous)), key=lambda i: trous[i].duree, reverse=True):
        trou = trous[rang]
        if not trou.notable:
            continue
        if any(abs(trou.x_milieu - x) < minimum for x in gardes):
            trous[rang] = replace(trou, notable=False)
            continue
        gardes.append(trou.x_milieu)
    return trous


def construire(
    points: list[tuple[float, int]],
    *,
    seuil_compression_s: float = SEUIL_COMPRESSION_S,
    rp: list[tuple[float, int]] | None = None,
    notion: str = "kills",
) -> Serie:
    """La série cumulative des gains, trous coupés et longs vides comprimés.

    Les `NaN` interrompent le trait de matplotlib : c'est ce qui distingue « il
    n'a rien fait » de « on n'a pas regardé ».

    `notion` fixe l'ÉCHELLE du plafond de vraisemblance : les dégâts se
    comptent par milliers, les kills par unités. La cumulative des dégâts était
    plate — chaque marche était rejetée comme un ré-épinglage de tracker.

    `rp` porte les relevés de `rank_score` sur la fenêtre. Le mode d'une partie
    n'existe nulle part dans l'API : un RP qui bouge est le seul signal qu'elle
    était classée — qu'il monte ou qu'il descende, une partie classée perdue
    reste une partie classée. Le RP n'entre PAS dans le gain : il éclaire la
    courbe, il n'y ajoute pas un kill.
    """
    instants_rp = sorted(t for t, _ in (rp or []))
    ecarts = [t2 - t1 for (t1, _), (t2, _) in zip(points, points[1:])]
    median = sorted(ecarts)[len(ecarts) // 2] if ecarts else 0.0
    seuil_coupure = max(median * FACTEUR_TROU, COUPURE_MIN_S)

    # La bande se dimensionne sur ce qui reste à l'échelle, connu seulement une
    # fois les vides repérés — d'où ce premier passage.
    comprimes = {i for i, dt in enumerate(ecarts) if dt > seuil_compression_s}
    utile = sum(dt for i, dt in enumerate(ecarts) if i not in comprimes)
    part = min(FRACTION_BANDE, FRACTION_BANDES_TOTAL / max(1, len(comprimes)))
    bande = max(BANDE_MIN_S, part * utile)
    # Un vide se juge sur la période couverte, pas sur les autres vides : une
    # nuit reste une nuit qu'il y ait une pause de plus ou de moins.
    couvert = (points[-1][0] - points[0][0]) if len(points) > 1 else 0.0

    xs: list[float] = [0.0]
    ys: list[float] = [0.0]
    classes: list[bool] = []
    trous: list[Trou] = []
    segments: list[Segment] = []
    x = 0.0
    total = 0.0
    segment_debut_t = points[0][0] if points else 0.0
    segment_debut_x = 0.0

    for rang, ((t_av, av), (t_ap, ap)) in enumerate(zip(points, points[1:])):
        dt = t_ap - t_av
        comprime = rang in comprimes
        coupe = comprime or dt > seuil_coupure
        if coupe:
            # Juste après le dernier relevé : le palier ne s'étale pas sur un
            # intervalle qu'on n'a pas mesuré.
            xs.append(x + min(1.0, dt / 2.0))
            ys.append(float("nan"))
            classes.append(False)
        if comprime:
            segments.append(Segment(segment_debut_t, t_av, segment_debut_x))
            debut_bande = x
            x += bande
            trous.append(
                Trou(t_av, t_ap, debut_bande, x, notable=dt >= PART_ANNOTATION * couvert)
            )
            segment_debut_t, segment_debut_x = t_ap, x
        else:
            x += dt

        ecart = ap - av
        if 0 < ecart <= plafond_plausible(dt, notion):
            total += ecart
        xs.append(x)
        ys.append(total)
        # Une marche coupée n'existe pas à l'écran : rien à colorer, et un
        # changement de RP pendant la nuit ne dit pas quand la partie a eu lieu.
        classes.append(
            not coupe
            and bisect_right(instants_rp, t_av) < bisect_right(instants_rp, t_ap)
        )

    if points:
        segments.append(Segment(segment_debut_t, points[-1][0], segment_debut_x))
    trous = _espacer_les_libelles(trous, x)
    return Serie(
        xs=xs, ys=ys, trous=trous, segments=segments,
        classes=classes, rp_connu=bool(instants_rp),
    )
