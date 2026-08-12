# bot/core/apex/history.py
"""Historique des compteurs Apex : ce qu'ils valaient, et quand.

L'API ne donne QUE des totaux à vie — `/games`, l'historique des matchs, nous
est fermé. « Combien de kills ce mois-ci » n'a donc aucune réponse directe :
il faut avoir relevé les compteurs au fil du temps et faire les différences
nous-mêmes. C'est tout l'objet de ce module.

## Ce qui rend le calcul délicat

Un compteur Apex n'est pas une série propre. Les trackers dépendent de ce que
le joueur ÉPINGLE en jeu, et la lecture somme ceux qui portent le même libellé
(cf. `reader.py`). Changer ses trackers fait donc bouger le total sans qu'une
seule partie ait été jouée — vers le bas si un tracker disparaît, vers le haut
s'il en apparaît un qui cumulait déjà des dizaines de milliers de kills.

D'où deux règles, et non une :
- on ne compte que les écarts POSITIFS entre relevés consécutifs (une chute
  n'est jamais une régression du joueur) ;
- on ignore les bonds INVRAISEMBLABLES (personne ne fait 300 kills en une
  minute), qui sont des artefacts de tracker, pas du jeu.

Sans la seconde, Wally annoncerait « +10 142 kills » en direct le jour où
Azraël réépingle un tracker.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

# Le fuseau dans lequel les gens vivent. « Aujourd'hui » et « ce mois-ci » se
# découpent ici, pas en UTC — la machine tourne en UTC et un live du soir se
# retrouverait à cheval sur deux jours.
PARIS = ZoneInfo("Europe/Paris")

# Le plafond de vraisemblance est un TAUX, pas un nombre fixe. Deux relevés
# peuvent être séparés de 30 secondes (la sonde du live) comme de deux semaines
# (quelqu'un qui redemande ses stats) : « 300 kills maximum » rejetterait le
# gain, bien réel, de la quinzaine.
#
# La base absorbe les intervalles courts, où un taux horaire ne pèse rien ; le
# taux prend le relais sur les longs. 150 kills/heure est déjà très au-dessus
# d'un joueur qui enchaîne (une partie dure une quinzaine de minutes).
#
# Limite assumée : sur un intervalle de plusieurs jours, le plafond dépasse la
# taille d'un saut de tracker moyen — un tel saut passerait. C'est le cas des
# relevés manuels espacés ; la sonde du live, elle, est protégée, et c'est elle
# qui alimente ce que Wally annonce à l'antenne.
MAX_GAIN_BASE = 100
MAX_GAIN_PAR_HEURE = 150


def plafond_plausible(secondes: float) -> float:
    """Gain maximal crédible sur un intervalle donné."""
    return MAX_GAIN_BASE + MAX_GAIN_PAR_HEURE * max(0.0, secondes) / 3600.0

# Un an d'historique : de quoi comparer deux mois et voir une saison passer.
RETENTION_JOURS = 400


@dataclass
class Progression:
    """Ce qu'un compteur a gagné sur une fenêtre, et ce qu'on a pu mesurer."""

    notion: str
    gain: int
    depuis: datetime            # début RÉEL de la mesure, pas celui demandé
    jusqua: datetime
    points: list[tuple[float, int]]   # (timestamp, valeur cumulée)
    complet: bool               # False si l'historique ne couvre pas la fenêtre

    @property
    def couverture_partielle(self) -> bool:
        return not self.complet


def _maintenant() -> float:
    return time.time()


def debut_de_periode(periode: str, *, maintenant: float | None = None) -> float:
    """Le début de « jour » / « semaine » / « mois », à l'heure de Paris."""
    now = datetime.fromtimestamp(maintenant or _maintenant(), PARIS)
    if periode == "jour":
        debut = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif periode == "semaine":
        debut = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif periode == "mois":
        debut = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"période inconnue : {periode!r}")
    return debut.timestamp()


# Une soirée de stream, large : « live » n'a pas de début consigné quelque part,
# on remonte donc d'une fenêtre fixe.
FENETRE_LIVE_S = 12 * 3600


def debut_de_fenetre(periode: str, *, maintenant: float | None = None) -> float:
    """Le début de la fenêtre d'une courbe, « live » compris.

    Trois endroits calculaient ce début : la réponse en conversation, l'image
    servie à l'overlay, et la garde qui décide si un panneau a de quoi être
    tracé. Deux vérités auraient suffi à laisser passer un panneau que l'image
    aurait ensuite refusé de tracer.
    """
    if (periode or "live") == "live":
        return (maintenant or _maintenant()) - FENETRE_LIVE_S
    return debut_de_periode(periode, maintenant=maintenant)


class ApexHistory:
    """Écrit les relevés, relit les progressions."""

    def __init__(self, db, *, retention_jours: int = RETENTION_JOURS) -> None:
        self._db = db
        self._retention = retention_jours
        # Dernière valeur écrite par (uid, notion) : évite de relire la base à
        # chaque passage pour savoir si quelque chose a bougé.
        self._dernier: dict[tuple[str, str], int] = {}
        self._derniere_purge = 0.0

    async def enregistrer(
        self, uid: str, stats: dict[str, int], *, maintenant: float | None = None
    ) -> int:
        """Consigne les compteurs qui ont CHANGÉ. Renvoie le nombre d'écritures."""
        uid = str(uid or "").strip()
        if not uid or not stats:
            return 0
        ts = maintenant or _maintenant()
        ecrits = 0
        for notion, valeur in stats.items():
            # L'API publie parfois du texte là où un nombre est attendu
            # (`ALStopPercent` vaut « No game this split »). Un compteur
            # illisible n'est pas un compteur à zéro : on ne le range pas, et
            # les autres notions du même relevé restent traitées.
            try:
                valeur = int(valeur)
            except (TypeError, ValueError):  # compteur illisible ≠ compteur à zéro
                continue
            cle = (uid, notion)
            connu = self._dernier.get(cle)
            if connu is None:
                connu = await self._derniere_valeur(uid, notion)
            if connu == valeur:
                continue
            await self._db.execute(
                "INSERT INTO apex_stat_points (uid, notion, value, recorded_at) "
                "VALUES (?, ?, ?, ?)",
                (uid, notion, valeur, ts),
            )
            self._dernier[cle] = valeur
            ecrits += 1
        if ecrits:
            logger.debug("ApexHistory: {n} compteur(s) consigné(s) pour {u}", n=ecrits, u=uid)
        await self._purger_si_besoin(ts)
        return ecrits

    async def _derniere_valeur(self, uid: str, notion: str) -> int | None:
        row = await self._db.fetch_one(
            "SELECT value FROM apex_stat_points WHERE uid = ? AND notion = ? "
            "ORDER BY recorded_at DESC LIMIT 1",
            (uid, notion),
        )
        return int(row["value"]) if row else None

    async def _purger_si_besoin(self, maintenant: float) -> None:
        """Purge au plus une fois par jour — la faire à chaque relevé ne servirait
        qu'à écrire sur la base pour ne rien supprimer."""
        if maintenant - self._derniere_purge < 86400:
            return
        self._derniere_purge = maintenant
        limite = maintenant - self._retention * 86400
        await self._db.execute(
            "DELETE FROM apex_stat_points WHERE recorded_at < ?", (limite,)
        )

    # Au-delà, on considère que le joueur a arrêté : une partie dure une
    # quinzaine de minutes, et la sonde passe toutes les 30 à 60 secondes.
    TROU_DE_SESSION_S = 1800.0

    # Notions rangées dans la même table mais qui ne PROUVENT pas qu'on a joué.
    # `rank_score` sert à colorer les parties classées ; son tout premier relevé
    # est écrit à la mise en service du suivi, personne ne jouant à ce
    # moment-là. Le 2026-08-12 il a suffi à ouvrir une « dernière session » à
    # 17h45 : « la courbe de ce stream » ne trouvait plus un seul kill, alors
    # que la session réelle avait commencé à 10h15 et valait 63 kills.
    #
    # Toute notion interne ajoutée ici plus tard doit rejoindre cet ensemble,
    # sinon elle redéfinira silencieusement ce qu'est une session.
    NOTIONS_INTERNES = ("rank_score",)

    async def debut_derniere_session(
        self, uid: str, *, trou_s: float | None = None, jours: int = 7,
        maintenant: float | None = None,
    ) -> float | None:
        """Le premier relevé du dernier bloc de jeu, ou None sans relevé.

        Sert quand on demande « la courbe de ce stream » alors que le stream est
        fini — ou que le bot a redémarré en plein live et ne connaît plus son
        `started_at`. Tous les compteurs de JEU comptent : les dégâts bougent
        presque à chaque partie, les kills non. Les notions internes
        (`NOTIONS_INTERNES`) sont écartées — elles ne prouvent pas qu'on a joué.

        Borné à `jours` : lire tout l'historique pour retrouver hier serait
        payer une année de relevés à chaque question.
        """
        seuil = trou_s if trou_s is not None else self.TROU_DE_SESSION_S
        depuis = (maintenant or _maintenant()) - jours * 86400
        exclues = ",".join("?" * len(self.NOTIONS_INTERNES))
        rows = await self._db.fetch_all(
            "SELECT DISTINCT recorded_at FROM apex_stat_points "
            f"WHERE uid = ? AND recorded_at >= ? AND notion NOT IN ({exclues}) "
            "ORDER BY recorded_at",
            (str(uid), depuis, *self.NOTIONS_INTERNES),
        )
        instants = [float(r["recorded_at"]) for r in rows or []]
        if not instants:
            return None
        debut = instants[0]
        for precedent, suivant in zip(instants, instants[1:]):
            if suivant - precedent > seuil:
                debut = suivant
        return debut

    async def releves(
        self, uid: str, notion: str, depuis: float
    ) -> list[tuple[float, int]]:
        """Les relevés bruts d'une notion sur une fenêtre, sans aucun calcul.

        Sert au RP, dont on ne veut pas le gain mais les INSTANTS de changement :
        une partie qui fait bouger le `rankScore` était classée, qu'il monte ou
        qu'il descende. Passer par `progression()` écraserait justement les
        baisses, qui portent ici autant d'information que les hausses.
        """
        rows = await self._db.fetch_all(
            "SELECT value, recorded_at FROM apex_stat_points "
            "WHERE uid = ? AND notion = ? AND recorded_at >= ? ORDER BY recorded_at",
            (str(uid), notion, depuis),
        )
        return [(float(r["recorded_at"]), int(r["value"])) for r in rows or []]

    async def rp_de_la_fenetre(self, uid: str, depuis: float) -> list[tuple[float, int]]:
        """Les relevés de RP d'une fenêtre, ou [] si l'observation ne la couvre pas.

        Le RP sert à distinguer les parties classées. Encore faut-il l'avoir
        relevé PENDANT toute la fenêtre : un premier relevé tombé au milieu ne
        dit rien des parties d'avant, et les afficher « non classées »
        affirmerait ce qu'on ne sait pas.

        Le cas s'est présenté en prod le 2026-08-12, quelques minutes après la
        mise en service du relevé : un unique point de RP aurait suffi à
        étiqueter vingt-quatre heures d'historique.

        Décidé ICI et pas chez les appelants : l'image Discord et la route de
        l'overlay tracent la même fenêtre, et deux jugements séparés finiraient
        par diverger.
        """
        premier = await self._db.fetch_one(
            "SELECT MIN(recorded_at) AS debut FROM apex_stat_points "
            "WHERE uid = ? AND notion = ?",
            (str(uid), "rank_score"),
        )
        debut = premier["debut"] if premier else None
        # Marge d'une session : `progression()` remonte jusque-là en arrière
        # pour trouver son point de départ, donc la courbe peut commencer AVANT
        # la fenêtre demandée. Sans cette marge, cette demi-heure serait jugée
        # sur une observation qui n'existait pas encore.
        if debut is None or float(debut) > depuis - self.TROU_DE_SESSION_S:
            return []
        return await self.releves(uid, "rank_score", depuis)

    async def progression(
        self, uid: str, notion: str, depuis: float, *, maintenant: float | None = None
    ) -> Progression | None:
        """Ce que `notion` a gagné depuis `depuis`, ou None sans aucun relevé.

        La fenêtre commence au premier relevé DISPONIBLE, qui peut être plus
        récent que celui demandé : `complet` le dit, et l'appelant doit le
        répercuter. Annoncer « ce mois-ci » un total qui commence au 12 serait
        un chiffre faux présenté comme complet.
        """
        ts = maintenant or _maintenant()
        rows = await self._db.fetch_all(
            "SELECT value, recorded_at FROM apex_stat_points "
            "WHERE uid = ? AND notion = ? AND recorded_at >= ? ORDER BY recorded_at",
            (str(uid), notion, depuis),
        )
        points = [(float(r["recorded_at"]), int(r["value"])) for r in rows or []]
        if not points:
            return None

        # Le relevé qui PRÉCÈDE la fenêtre en donne le vrai point de départ :
        # sans lui, le premier gain de la période serait perdu — deux relevés à
        # cheval sur minuit appartiennent à la journée qui commence.
        #
        # Mais SEULEMENT s'il est proche. Le 2026-08-12, « la courbe de ce
        # stream » annonçait +74 kills là où l'image en traçait 63 : le relevé
        # précédent datait de neuf heures, et les onze kills de la nuit
        # tombaient dans le stream du matin. On ne sait pas quand ils ont été
        # faits — donc on ne les attribue à personne.
        avant = await self._db.fetch_one(
            "SELECT value, recorded_at FROM apex_stat_points "
            "WHERE uid = ? AND notion = ? AND recorded_at < ? AND recorded_at >= ? "
            "ORDER BY recorded_at DESC LIMIT 1",
            (str(uid), notion, depuis, depuis - self.TROU_DE_SESSION_S),
        )
        if avant is not None:
            points.insert(0, (float(avant["recorded_at"]), int(avant["value"])))
        # Complète aussi quand la fenêtre commence juste avant son premier
        # relevé : « ce stream » démarre quelques minutes avant la première
        # partie, il n'y manque rien et annoncer un minimum serait une réserve
        # inutile.
        complet = avant is not None or (points[0][0] - depuis) <= self.TROU_DE_SESSION_S

        gain = self._gain(points, uid=str(uid), notion=notion)
        return Progression(
            notion=notion,
            gain=gain,
            depuis=datetime.fromtimestamp(points[0][0], PARIS),
            jusqua=datetime.fromtimestamp(max(points[-1][0], ts), PARIS),
            points=points,
            complet=complet,
        )

    def _gain(self, points: list[tuple[float, int]], *, uid: str, notion: str) -> int:
        """Somme des écarts positifs plausibles entre relevés consécutifs."""
        total = 0
        for (t_avant, avant), (t_apres, apres) in zip(points, points[1:]):
            ecart = apres - avant
            if ecart <= 0:
                continue
            if ecart > plafond_plausible(t_apres - t_avant):
                # Un tracker vient d'apparaître ou de fusionner : ce n'est pas
                # du jeu. On le dit fort — un chiffre absurde diffusé à l'écran
                # coûte plus cher qu'une ligne de log.
                logger.warning(
                    "ApexHistory: saut de {e} sur {n} ({u}) en {d:.0f} s — "
                    "tracker modifié, écart ignoré",
                    e=ecart, n=notion, u=uid, d=t_apres - t_avant,
                )
                continue
            total += ecart
        return total

    async def depuis_derniere_consultation(
        self, uid: str, notion: str, *, avant: float, ecart_min_s: float = 3600.0
    ) -> Progression | None:
        """Ce que `notion` a gagné entre l'avant-dernier relevé et maintenant.

        Sert le « t'as fait 124 kills de plus depuis la dernière fois que tu me
        l'as demandé » : ces comptes-là ne sont pas sondés automatiquement, leur
        historique est fait des consultations elles-mêmes.

        `avant` est l'instant du relevé courant : on cherche le dernier point
        qui le PRÉCÈDE. Rien si cette consultation précédente date de moins de
        `ecart_min_s` — « +0 kill depuis tout à l'heure » n'apprend rien à
        personne, et redemander deux fois de suite est fréquent.
        """
        precedent = await self._db.fetch_one(
            "SELECT value, recorded_at FROM apex_stat_points "
            "WHERE uid = ? AND notion = ? AND recorded_at < ? "
            "ORDER BY recorded_at DESC LIMIT 1",
            (str(uid), notion, avant),
        )
        if precedent is None:
            return None
        if avant - float(precedent["recorded_at"]) < ecart_min_s:
            return None
        return await self.progression(
            uid, notion, float(precedent["recorded_at"]) - 0.001
        )
