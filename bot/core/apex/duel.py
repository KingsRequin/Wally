# bot/core/apex/duel.py
"""Le duel Apex : machine à états PURE, sans réseau ni I/O.

Elle reçoit des relevés et rend des décisions ; tout se teste en rejouant une
séquence, sans toucher l'API. Le réseau, la persistance et les effets vivent
dans `duel_runner.py`.

Spec : docs/superpowers/specs/2026-08-13-apex-duel-points-chaine-design.md
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum

# Au-delà de ce delta sur une seule manche, ce n'est pas un score : c'est un
# tracker qu'on vient d'épingler. Mesuré le 2026-08-13 : +7793 d'un coup, sans
# un kill joué. Le plafond est volontairement haut — les records connus en Apex
# tournent autour de 25-30 kills — pour ne jamais mordre sur un vrai résultat.
PLAFOND_KILLS_MANCHE = 30

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
    # Ce qui se montre à l'écran sous chaque camp — la légende jouée et le
    # niveau du compte — lu dans le MÊME profil que les kills, donc sans une
    # requête de plus. Facultatif : un relevé fictif (API muette, tour de
    # résolution) n'en porte pas, et une absence ne vaut jamais zéro.
    camp_azrael: dict = field(default_factory=dict)
    camp_viewer: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Evenement:
    type: str
    donnees: dict


@dataclass
class Duel:
    viewer_nom: str
    viewer_uid: str
    azrael_uid: str
    # L'identifiant Twitch BRUT du duelliste (« 105904256 »), porté par
    # l'événement de redemption. Il ne sert qu'à la trace mémoire de fin de
    # duel : `memory.add()` veut l'id, pas le pseudo — un pseudo change, et
    # deux comptes peuvent porter successivement le même. Vide quand la
    # redemption ne l'a pas donné : la trace est alors sautée, jamais devinée.
    viewer_id: str = ""
    manches: int = 3
    redemption_id: str = ""
    etat: Etat = Etat.RESOLUTION
    # Rien de figé en dur : ce sont des champs, donc sérialisés et modifiables
    # par duel, jamais des constantes lues directement dans avancer().
    attente_squad_s: float = ATTENTE_SQUAD_S
    plafond_kills_manche: int = PLAFOND_KILLS_MANCHE
    # Un score par manche jouée : {"azrael": int|None, "viewer": int|None}.
    # Les deux valent None dès que la manche n'est pas mesurable pour L'UN
    # des deux joueurs — jamais un score réel comparé à une absence de mesure.
    scores: list[dict] = field(default_factory=list)
    # Dernier état connu de chaque camp : {"azrael": {"legende": …, "niveau": …}}.
    # Sert au sous-titre du tableau à l'écran, jamais à l'arbitrage.
    camps: dict = field(default_factory=dict)
    _base_azrael: dict = field(default_factory=dict)
    _base_viewer: dict = field(default_factory=dict)
    _t_attente: float | None = None
    # Debounce anti-hoquet : un flag de présence EA peut mentir sur une seule
    # lecture. Deux relevés consécutifs concordants sont exigés pour changer
    # d'état (entrée en partie comme retour au lobby). Volontairement pas
    # sérialisés : perdre une confirmation en attente sur un rebuild ne fait
    # que retarder la transition d'un cycle de sonde, sans jamais la fausser.
    _pending_debut: bool = False
    _pending_fin: bool = False

    # -- Totaux -------------------------------------------------------------
    @property
    def total_azrael(self) -> int:
        return sum(s["azrael"] or 0 for s in self.scores)

    @property
    def total_viewer(self) -> int:
        return sum(s["viewer"] or 0 for s in self.scores)

    @property
    def mesurable(self) -> bool:
        """Au moins une manche a été MESURÉE — donc les totaux veulent dire
        quelque chose.

        Faux tant qu'aucune ne l'est : `total_azrael` et `total_viewer` valent
        alors 0 par sommation de `None or 0`, et les annoncer serait affirmer
        un « 0 — 0 » que personne n'a mesuré. C'est exactement le zéro inventé
        que le reste du code refuse partout — sur un duel joué en Mixtape,
        chaque manche est déclarée non mesurable et le total dirait pourtant
        zéro à zéro avec aplomb.

        Lu par le bloc de perception (`prompts.bloc_duel_en_cours`) et par
        l'outil `duel_apex` : les deux disaient l'inverse de l'annonceur, qui
        refuse déjà d'afficher un tableau non mesurable.
        """
        return any(s["azrael"] is not None or s["viewer"] is not None
                   for s in self.scores)

    @property
    def manche_courante(self) -> int:
        """1-indexée, pour l'affichage."""
        return min(len(self.scores) + 1, self.manches)

    def demarrer_attente_squad(self) -> None:
        """Le compte est résolu : l'attente du squad repart à neuf.

        Le minuteur est REMIS À ZÉRO, il ne s'hérite pas de la résolution :
        sinon un viewer qui a mis dix minutes à trouver son uid n'aurait plus
        que cinq minutes pour rejoindre le squad, et serait abandonné avant
        d'avoir joué.
        """
        self.etat = Etat.ATTENTE_SQUAD
        self._t_attente = None

    def abandonner(self, motif: str) -> list[Evenement]:
        """Abandon décidé de l'EXTÉRIEUR, avec remboursement.

        La machine ne peut pas le déduire seule : elle ne voit pas les relevés
        qui n'arrivent PAS. Le seul à savoir que l'API est muette, c'est le
        runner qui l'interroge — d'où cette entrée.

        Le remboursement est inconditionnel, à la différence de l'abandon
        d'ENTRE_MANCHES : là-bas c'est le duelliste qui n'est pas revenu, ici
        c'est la mesure qui a disparu. Le viewer n'y est pour rien.
        """
        if self.etat in (Etat.VERDICT, Etat.ABANDON):
            return []
        self.etat = Etat.ABANDON
        return [Evenement("abandon", {
            "rembourser": True, "motif": motif,
            "manches_jouees": len(self.scores),
        })]

    def recommencer(self) -> None:
        """Remet les compteurs à zéro, même duelliste (§7 de la spec)."""
        self.scores = []
        self._base_azrael = {}
        self._base_viewer = {}
        self._t_attente = None
        self._pending_debut = False
        self._pending_fin = False
        self.etat = Etat.ATTENTE_SQUAD

    # -- Persistance --------------------------------------------------------
    def to_dict(self) -> dict:
        """Une PHOTO de l'état, jamais une référence.

        Un appelant qui capture ce dict et laisse le duel continuer avant de
        l'écrire (I/O async) ne doit jamais voir cette suite bouger la
        capture — sinon une manche encore en cours à l'instant du snapshot se
        retrouve comptée deux fois à la reprise.
        """
        return {
            "viewer_nom": self.viewer_nom, "viewer_uid": self.viewer_uid,
            "viewer_id": self.viewer_id,
            "azrael_uid": self.azrael_uid, "manches": self.manches,
            "redemption_id": self.redemption_id, "etat": self.etat.value,
            "attente_squad_s": self.attente_squad_s,
            "plafond_kills_manche": self.plafond_kills_manche,
            "scores": copy.deepcopy(self.scores),
            "camps": copy.deepcopy(self.camps),
            "base_azrael": copy.deepcopy(self._base_azrael),
            "base_viewer": copy.deepcopy(self._base_viewer),
            "t_attente": self._t_attente,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Duel":
        duel = cls(
            viewer_nom=d.get("viewer_nom", ""), viewer_uid=d.get("viewer_uid", ""),
            viewer_id=str(d.get("viewer_id") or ""),
            azrael_uid=d.get("azrael_uid", ""), manches=int(d.get("manches", 3)),
            redemption_id=d.get("redemption_id", ""),
            etat=Etat(d.get("etat", Etat.RESOLUTION.value)),
            attente_squad_s=float(d.get("attente_squad_s", ATTENTE_SQUAD_S)),
            plafond_kills_manche=int(d.get("plafond_kills_manche", PLAFOND_KILLS_MANCHE)),
            scores=copy.deepcopy(d.get("scores") or []),
            camps=copy.deepcopy(d.get("camps") or {}),
        )
        duel._base_azrael = copy.deepcopy(d.get("base_azrael") or {})
        duel._base_viewer = copy.deepcopy(d.get("base_viewer") or {})
        duel._t_attente = d.get("t_attente")
        return duel

    # -- Le cœur ------------------------------------------------------------
    def avancer(self, r: Releve) -> list[Evenement]:
        """Fait avancer le duel d'un relevé, et rend ce qu'il faut annoncer."""
        if self.etat in (Etat.VERDICT, Etat.ABANDON):
            return []
        self._noter_camps(r)

        if self.etat is Etat.RESOLUTION:
            # La résolution a le MÊME délai que l'attente du squad, et pour la
            # même raison : un viewer qui a payé et ne répond plus ne doit pas
            # laisser le duel peuplé indéfiniment. Sans ce délai, ses points ne
            # revenaient jamais et TOUT acheteur suivant était refusé « un duel
            # est déjà en cours » — sans limite de temps ni la moindre trace.
            # Seul le temps compte ici : rien du relevé n'est lu, il n'y a pas
            # encore de compte à sonder.
            if self._t_attente is None:
                self._t_attente = r.t
                return []
            if r.t - self._t_attente < self.attente_squad_s:
                return []
            self.etat = Etat.ABANDON
            return [Evenement("abandon", {
                "rembourser": True,
                "motif": "le compte Apex n'a jamais été donné dans le délai",
            })]

        if self.etat in (Etat.ATTENTE_SQUAD, Etat.ENTRE_MANCHES):
            if self._t_attente is None:
                self._t_attente = r.t
            # Les DEUX en partie : la manche commence. On ne peut pas vérifier
            # qu'ils sont dans le même squad — l'API ne donne pas la composition
            # d'une équipe (§2 de la spec). Il faut DEUX relevés consécutifs
            # concordants pour confirmer : un flag de présence EA hoquette.
            if r.azrael_in_game and r.viewer_in_game:
                if not self._pending_debut:
                    self._pending_debut = True
                    return []
                self._pending_debut = False
                self._base_azrael = dict(r.kills_azrael)
                self._base_viewer = dict(r.kills_viewer)
                self._t_attente = None
                self.etat = Etat.MANCHE
                # Les totaux voyagent AUSSI au début de manche : c'est ce qui
                # permet d'afficher le tableau à l'écran là aussi (§11 de la
                # spec). `total_mesurable` et `manches_jouees` disent à
                # l'affichage s'il a le droit d'écrire ces chiffres : avant la
                # première manche, un « 0 — 0 » ne prétend rien ; après une
                # manche non mesurable, il affirmerait un score que personne
                # n'a compté.
                return [Evenement("manche_debut", {
                    "manche": self.manche_courante, "sur": self.manches,
                    "manches_jouees": len(self.scores),
                    "total_azrael": self.total_azrael,
                    "total_viewer": self.total_viewer,
                    "total_mesurable": self.mesurable,
                    "camps": copy.deepcopy(self.camps),
                })]
            self._pending_debut = False
            if r.t - self._t_attente < self.attente_squad_s:
                return []
            # Timeout. Le motif dépend de l'état : depuis ATTENTE_SQUAD rien
            # n'a commencé, depuis ENTRE_MANCHES le duel s'est arrêté EN
            # COURS. Le même message pour les deux ferait annoncer « personne
            # n'a rejoint le squad » à un viewer qui vient de gagner sa manche.
            if self.etat is Etat.ATTENTE_SQUAD:
                self.etat = Etat.ABANDON
                return [Evenement("abandon", {
                    "rembourser": True,
                    "motif": "personne n'a rejoint le squad dans le délai",
                })]

            # ENTRE_MANCHES : au moins une manche a été JOUÉE — reste à savoir
            # si elle a été MESURÉE. Sans mesure, il n'y a rien à arbitrer et
            # annoncer un 0-0 serait le faux match nul qu'on refuse partout
            # ailleurs : on rembourse.
            if self._aucun_kill_compte():
                self.etat = Etat.ABANDON
                return [Evenement("abandon", {
                    "rembourser": True,
                    "motif": ("le duel s'est arrêté en cours de route, et aucun "
                              "kill n'avait pu être compté — rien à arbitrer"),
                    "manches_jouees": len(self.scores),
                })]
            # Une manche mesurée au moins : PAS de remboursement. Rembourser
            # qui part après avoir joué encouragerait l'abandon dès qu'on perd,
            # et l'API ne distingue pas un départ volontaire d'une coupure de
            # stream. Le verdict porte alors sur les manches réellement jouées.
            evts = [Evenement("abandon", {
                "rembourser": False,
                "motif": (f"le duel s'est arrêté en cours, après la manche "
                          f"{len(self.scores)}/{self.manches} — pas de retour "
                          f"dans le délai"),
                "manches_jouees": len(self.scores),
            })]
            evts.extend(self._clore())
            return evts

        if self.etat is Etat.MANCHE:
            # C'est le retour au lobby d'Azraël qui clôt la manche : les
            # compteurs y sont déjà à jour. Deux relevés consécutifs "hors
            # partie" sont exigés — un hoquet isolé du flag de présence ne
            # doit ni clore la manche en cours ni en ouvrir une autre.
            if not r.azrael_in_game:
                if not self._pending_fin:
                    self._pending_fin = True
                    return []
                self._pending_fin = False
                sa = score_manche(self._base_azrael, r.kills_azrael,
                                  plafond=self.plafond_kills_manche)
                sv = score_manche(self._base_viewer, r.kills_viewer,
                                  plafond=self.plafond_kills_manche)
                # Mesurable seulement si LES DEUX côtés le sont : on ne compare
                # jamais un score réel à une absence de mesure. Une manche non
                # mesurable pour un seul joueur ne compte pour personne.
                mesurable = sa is not None and sv is not None
                self.scores.append({
                    "azrael": sa if mesurable else None,
                    "viewer": sv if mesurable else None,
                })
                # `azrael`/`viewer` sont les deltas BRUTS, à n'annoncer que si
                # `mesurable` : quand un seul côté est lisible, les dire tels
                # quels informe (« je t'ai vu en faire 3, mais rien de ton
                # côté ») sans jamais rentrer dans les totaux ci-dessous.
                evts = [Evenement("manche_fin", {
                    "manche": len(self.scores), "sur": self.manches,
                    "azrael": sa, "viewer": sv, "mesurable": mesurable,
                    "total_azrael": self.total_azrael, "total_viewer": self.total_viewer,
                    "camps": copy.deepcopy(self.camps),
                })]
                if len(self.scores) >= self.manches:
                    evts.extend(self._clore())
                else:
                    self.etat = Etat.ENTRE_MANCHES
                    self._t_attente = None
                return evts
            self._pending_fin = False
            return []

        return []

    def _noter_camps(self, r: Releve) -> None:
        """Retient le DERNIER état connu de chaque camp (légende, niveau).

        Retenu, et non relu à la demande : le verdict se rend parfois depuis un
        relevé fictif (abandon entre deux manches, API muette) qui ne porte
        rien. Une valeur vide n'écrase jamais une valeur connue — une donnée
        absente n'est pas une donnée, et surtout pas un zéro.
        """
        for cote, camp in (("azrael", r.camp_azrael), ("viewer", r.camp_viewer)):
            for cle, valeur in (camp or {}).items():
                if valeur:
                    self.camps.setdefault(cote, {})[cle] = valeur

    def _aucun_kill_compte(self) -> bool:
        """Aucun kill compté de tout le duel — quelle qu'en soit la raison.

        Un delta de 0 MESURÉ (vraie Mixtape : les trackers sont présents mais
        figés, `score_manche` rend 0) doit compter ici exactement comme un
        dict vide (API muette, `score_manche` rend None). Une condition qui ne
        chercherait que des `None` laisserait passer la Mixtape mesurée le
        2026-08-13 — 10 kills joués, neuf trackers figés — et annoncerait
        « 0-0, match nul » à deux joueurs qui ont fait trois parties.
        """
        return all((s["azrael"] or 0) == 0 and (s["viewer"] or 0) == 0
                   for s in self.scores)

    def _clore(self) -> list[Evenement]:
        """Verdict, ou abandon si aucun kill n'a jamais été compté nulle part."""
        if self._aucun_kill_compte():
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
            "scores": copy.deepcopy(self.scores),
            "camps": copy.deepcopy(self.camps),
        })]


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
