# bot/core/apex/duel.py
"""Le duel Apex : machine à états PURE, sans réseau ni I/O.

Elle reçoit des relevés et rend des décisions ; tout se teste en rejouant une
séquence, sans toucher l'API. Le réseau, la persistance et les effets vivent
dans `duel_runner.py`.

Spec : docs/superpowers/specs/2026-08-13-apex-duel-points-chaine-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Le viewer a ce délai pour rejoindre le squad. Au-delà, remboursement : un
# viewer qui a payé et ne voit rien est le pire résultat possible.
ATTENTE_SQUAD_S = 15 * 60


class Etat(str, Enum):
    RESOLUTION = "resolution"
    ATTENTE_SQUAD = "attente_squad"
    MANCHE = "manche"
    ENTRE_MANCHES = "entre_manches"
    VERDICT = "verdict"
    ABANDON = "abandon"


@dataclass(frozen=True)
class Releve:
    t: float
    azrael_in_game: bool
    viewer_in_game: bool
    kills_azrael: dict[str, int]
    kills_viewer: dict[str, int]


@dataclass(frozen=True)
class Evenement:
    type: str
    donnees: dict


@dataclass
class Duel:
    viewer_nom: str
    viewer_uid: str
    azrael_uid: str
    manches: int = 3
    redemption_id: str = ""
    etat: Etat = Etat.RESOLUTION
    # Un score par manche jouée : {"azrael": int|None, "viewer": int|None}
    scores: list[dict] = field(default_factory=list)
    _base_azrael: dict = field(default_factory=dict)
    _base_viewer: dict = field(default_factory=dict)
    _t_attente: float | None = None

    # -- Totaux -------------------------------------------------------------
    @property
    def total_azrael(self) -> int:
        return sum(s["azrael"] or 0 for s in self.scores)

    @property
    def total_viewer(self) -> int:
        return sum(s["viewer"] or 0 for s in self.scores)

    @property
    def manche_courante(self) -> int:
        """1-indexée, pour l'affichage."""
        return min(len(self.scores) + 1, self.manches)

    def recommencer(self) -> None:
        """Remet les compteurs à zéro, même duelliste (§7 de la spec)."""
        self.scores = []
        self._base_azrael = {}
        self._base_viewer = {}
        self._t_attente = None
        self.etat = Etat.ATTENTE_SQUAD

    # -- Persistance --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "viewer_nom": self.viewer_nom, "viewer_uid": self.viewer_uid,
            "azrael_uid": self.azrael_uid, "manches": self.manches,
            "redemption_id": self.redemption_id, "etat": self.etat.value,
            "scores": self.scores, "base_azrael": self._base_azrael,
            "base_viewer": self._base_viewer, "t_attente": self._t_attente,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Duel":
        duel = cls(
            viewer_nom=d.get("viewer_nom", ""), viewer_uid=d.get("viewer_uid", ""),
            azrael_uid=d.get("azrael_uid", ""), manches=int(d.get("manches", 3)),
            redemption_id=d.get("redemption_id", ""),
            etat=Etat(d.get("etat", Etat.RESOLUTION.value)),
            scores=list(d.get("scores") or []),
        )
        duel._base_azrael = dict(d.get("base_azrael") or {})
        duel._base_viewer = dict(d.get("base_viewer") or {})
        duel._t_attente = d.get("t_attente")
        return duel

    # -- Le cœur ------------------------------------------------------------
    def avancer(self, r: Releve) -> list[Evenement]:
        """Fait avancer le duel d'un relevé, et rend ce qu'il faut annoncer."""
        if self.etat in (Etat.VERDICT, Etat.ABANDON, Etat.RESOLUTION):
            return []

        if self.etat in (Etat.ATTENTE_SQUAD, Etat.ENTRE_MANCHES):
            if self._t_attente is None:
                self._t_attente = r.t
            # Les DEUX en partie : la manche commence. On ne peut pas vérifier
            # qu'ils sont dans le même squad — l'API ne donne pas la composition
            # d'une équipe (§2 de la spec).
            if r.azrael_in_game and r.viewer_in_game:
                self._base_azrael = dict(r.kills_azrael)
                self._base_viewer = dict(r.kills_viewer)
                self._t_attente = None
                self.etat = Etat.MANCHE
                return [Evenement("manche_debut", {"manche": self.manche_courante,
                                                   "sur": self.manches})]
            if r.t - self._t_attente >= ATTENTE_SQUAD_S:
                self.etat = Etat.ABANDON
                return [Evenement("abandon", {
                    "rembourser": True,
                    "motif": "personne n'a rejoint le squad dans le délai",
                })]
            return []

        if self.etat is Etat.MANCHE:
            # C'est le retour au lobby d'Azraël qui clôt la manche : les
            # compteurs y sont déjà à jour, mesuré deux fois sur deux.
            if r.azrael_in_game:
                return []
            sa = score_manche(self._base_azrael, r.kills_azrael)
            sv = score_manche(self._base_viewer, r.kills_viewer)
            self.scores.append({"azrael": sa, "viewer": sv})
            evts = [Evenement("manche_fin", {
                "manche": len(self.scores), "sur": self.manches,
                "azrael": sa, "viewer": sv,
                "mesurable": sa is not None or sv is not None,
                "total_azrael": self.total_azrael, "total_viewer": self.total_viewer,
            })]
            if len(self.scores) >= self.manches:
                evts.extend(self._clore())
            else:
                self.etat = Etat.ENTRE_MANCHES
                self._t_attente = None
            return evts

        return []

    def _clore(self) -> list[Evenement]:
        """Verdict, ou abandon si rien n'a jamais été mesurable."""
        # Aucune manche mesurable : Mixtape (10 kills → 0 compteur, mesuré) ou
        # API muette. Dans les deux cas le duel n'est pas arbitrable. Annoncer
        # un match nul serait mentir avec aplomb.
        if all(s["azrael"] is None and s["viewer"] is None for s in self.scores):
            self.etat = Etat.ABANDON
            return [Evenement("abandon", {
                "rembourser": True,
                "motif": ("aucun kill n'a été enregistré de tout le duel — "
                          "la Mixtape ne compte pas les kills, ou l'API n'a rien vu"),
            })]
        self.etat = Etat.VERDICT
        a, v = self.total_azrael, self.total_viewer
        return [Evenement("verdict", {
            "azrael": a, "viewer": v,
            "gagnant": None if a == v else ("azrael" if a > v else "viewer"),
            "scores": list(self.scores),
        })]


# Au-delà de ce delta sur une seule manche, ce n'est pas un score : c'est un
# tracker qu'on vient d'épingler. Mesuré le 2026-08-13 : +7793 d'un coup, sans
# un kill joué. Le plafond est volontairement haut — les records connus en Apex
# tournent autour de 25-30 kills — pour ne jamais mordre sur un vrai résultat.
PLAFOND_KILLS_MANCHE = 30


def score_manche(avant: dict[str, int], apres: dict[str, int],
                 *, plafond: int = PLAFOND_KILLS_MANCHE) -> int | None:
    """Les kills faits entre deux relevés, ou None si la manche n'est pas mesurable.

    Le MAXIMUM des deltas, jamais leur somme : les quatre trackers bougent du
    même montant à chaque kill (4 kills → +4 partout), donc les additionner
    donnerait 16. C'est le piège exactement symétrique de la règle d'addition
    qui vaut, elle, pour un total carrière.

    Seules les clés présentes dans les DEUX relevés comptent : un tracker apparu
    en cours de manche n'a pas de point de départ.

    `None` et non `0` quand rien n'est mesurable : un zéro inventé est un
    mensonge, pas une valeur par défaut. La Mixtape, qui n'incrémente aucun
    compteur (10 kills → 0, mesuré), tombe dans ce cas.
    """
    deltas = []
    for cle, depart in avant.items():
        arrivee = apres.get(cle)
        if arrivee is None:
            continue
        delta = arrivee - depart
        if delta < 0 or delta > plafond:
            continue
        deltas.append(delta)
    if not deltas:
        return None
    return max(deltas)
