"""Le moteur du sondage Discord : qui a voté quoi, et qui gagne.

Séparé du sondage de l'overlay (`OverlayNarrator._poll`) et il doit le rester :
là-bas le chat du live vote en tapant un numéro, ici les gens cliquent une
réaction sous un embed. Les mêler ferait qu'un sondage Discord écrase celui du
live — et l'overlay n'en tient qu'un seul à la fois.

Ce module ne connaît ni Discord ni Pillow : il compte des votes. C'est ce qui le
rend testable sans serveur, et ce qui rend le reste (image, réactions, cadence
d'édition) remplaçable sans y toucher.

⚠️ **L'échéance se range en temps MURAL** (`time.time()`), jamais en
`time.monotonic()` : un sondage de dix minutes traverse volontiers un rebuild,
et un monotonic relu dans un autre process donne une échéance absurde. Le piège
est déjà documenté dans `etat_persistant.py`, il vaut ici aussi.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

# Un emoji par option. Dix serait possible (🔟), mais un sondage à dix branches
# ne se lit plus sous un embed — et l'overlay s'arrête à quatre.
EMOJIS_VOTE: tuple[str, ...] = (
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣",
)
MAX_OPTIONS = len(EMOJIS_VOTE)
MIN_OPTIONS = 2
MAX_QUESTION = 140
MAX_OPTION = 50
# Le sélecteur de présentation : selon le client, un même emoji arrive avec ou
# sans. Comparer les chaînes brutes fait rater un vote sur deux, en silence.
_VARIATEUR = "️"


def _nu(emoji: str) -> str:
    return (emoji or "").replace(_VARIATEUR, "")


_INDEX_PAR_EMOJI: dict[str, int] = {_nu(e): i for i, e in enumerate(EMOJIS_VOTE)}


def emoji_pour(index: int) -> str:
    """L'emoji de vote d'une option, tel que Wally le pose sous le message."""
    return EMOJIS_VOTE[index]


def index_de_emoji(emoji: str) -> Optional[int]:
    """L'option visée par une réaction, ou None si ce n'est pas un vote."""
    return _INDEX_PAR_EMOJI.get(_nu(emoji))


@dataclass
class Resultat:
    """Le dépouillement à un instant donné."""

    tally: list[int]
    total: int
    gagnant: Optional[int]   # index de l'option en tête, None si personne
    egalite: bool


@dataclass
class Sondage:
    question: str
    options: list[str]
    channel_id: int
    auteur: str = ""
    message_id: int = 0
    ends_at: Optional[float] = None       # temps MURAL, cf. l'en-tête
    # La durée demandée, gardée parce que `ends_at` seul ne dit pas quelle
    # FRACTION du temps reste — et c'est cette fraction que dessine le sablier.
    duree_s: Optional[float] = None
    ping: bool = False
    votes: dict[str, int] = field(default_factory=dict)
    clos: bool = False

    # ── vote ────────────────────────────────────────────────────────────────

    def voter(self, user_id: str, index: int) -> bool:
        """Pose le vote de quelqu'un. Rend True si l'affichage doit bouger.

        Un second vote REMPLACE le premier : c'est la règle demandée, et elle
        vaut aussi bien quand la réaction précédente a pu être retirée que
        quand elle n'a pas pu l'être.
        """
        if self.clos or not 0 <= index < len(self.options):
            return False
        if self.votes.get(user_id) == index:
            return False
        self.votes[user_id] = index
        return True

    def retirer(self, user_id: str, index: int) -> bool:
        """Retire un vote quand la personne décoche SA réaction courante.

        La garde sur l'index est le cœur : quand Wally retire l'ancienne
        réaction d'un changement d'avis, Discord renvoie l'événement de retrait.
        Sans cette condition, l'écho effacerait le vote qui vient d'être pris.
        """
        if self.clos or self.votes.get(user_id) != index:
            return False
        del self.votes[user_id]
        return True

    def recompter(self, reactions: dict[str, list[str]]) -> None:
        """Reconstruit les votes à partir de ce que Discord AFFICHE.

        C'est la vérité au redémarrage : les votes rangés en base peuvent être
        en retard d'une écriture, et surtout les réactions posées pendant que le
        process était éteint n'ont produit aucun événement. Le message, lui, les
        porte toutes.

        Un double votant survivant (Wally n'a pas pu retirer sa première
        réaction) est tranché par l'ordre des options — le premier emoji fait
        foi, comme le repli sans `Gérer les messages`.
        """
        votes: dict[str, int] = {}
        indexes = sorted(
            (i, users) for emoji, users in reactions.items()
            if (i := index_de_emoji(emoji)) is not None and i < len(self.options)
        )
        for index, users in indexes:
            for user_id in users:
                votes.setdefault(str(user_id), index)
        self.votes = votes

    # ── temps ───────────────────────────────────────────────────────────────

    def restant(self, maintenant: Optional[float] = None) -> Optional[float]:
        if self.ends_at is None:
            return None
        return max(0.0, self.ends_at - (maintenant if maintenant is not None
                                        else time.time()))

    def expire(self, maintenant: Optional[float] = None) -> bool:
        reste = self.restant(maintenant)
        return reste is not None and reste <= 0.0

    # ── dépouillement ───────────────────────────────────────────────────────

    def depouiller(self) -> Resultat:
        tally = [0] * len(self.options)
        for index in self.votes.values():
            if 0 <= index < len(tally):
                tally[index] += 1
        total = sum(tally)
        if not total:
            return Resultat(tally=tally, total=0, gagnant=None, egalite=False)
        tete = max(range(len(tally)), key=lambda i: tally[i])
        egalite = tally.count(tally[tete]) > 1
        return Resultat(tally=tally, total=total,
                        gagnant=None if egalite else tete, egalite=egalite)

    def ligne_resultat(self) -> str:
        """Ce que Wally saura DIRE du sondage — dans le chat, ou plus tard."""
        r = self.depouiller()
        if not r.total:
            return f"Sondage « {self.question} » : aucun vote."
        if r.egalite:
            hauts = [self.options[i] for i, n in enumerate(r.tally)
                     if n == max(r.tally)]
            return (f"Sondage « {self.question} » : égalité entre "
                    f"{' et '.join(hauts)} ({max(r.tally)} voix chacun, "
                    f"{r.total} votes).")
        assert r.gagnant is not None
        return (f"Sondage « {self.question} » : « {self.options[r.gagnant]} » "
                f"l'emporte avec {r.tally[r.gagnant]} voix sur {r.total}.")

    # ── persistance ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": list(self.options),
            "channel_id": self.channel_id,
            "auteur": self.auteur,
            "message_id": self.message_id,
            "ends_at": self.ends_at,
            "duree_s": self.duree_s,
            "ping": self.ping,
            "votes": dict(self.votes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Sondage":
        return cls(
            question=str(data["question"]),
            options=[str(o) for o in data["options"]],
            channel_id=int(data["channel_id"]),
            auteur=str(data.get("auteur") or ""),
            message_id=int(data.get("message_id") or 0),
            ends_at=None if data.get("ends_at") is None else float(data["ends_at"]),
            duree_s=None if data.get("duree_s") is None else float(data["duree_s"]),
            ping=bool(data.get("ping")),
            votes={str(k): int(v) for k, v in (data.get("votes") or {}).items()},
        )


def creer(question: str, options: list[str], *, channel_id: int,
          auteur: str = "", duree_s: Optional[float] = None,
          ping: bool = False,
          maintenant: Optional[float] = None) -> Optional[Sondage]:
    """Fabrique un sondage valide, ou None si la demande n'en est pas un."""
    question = (question or "").strip()[:MAX_QUESTION]
    propres = [str(o).strip()[:MAX_OPTION] for o in (options or [])
               if str(o).strip()][:MAX_OPTIONS]
    if not question or len(propres) < MIN_OPTIONS:
        return None
    ends_at = None
    if duree_s:
        base = maintenant if maintenant is not None else time.time()
        ends_at = base + float(duree_s)
    return Sondage(question=question, options=propres, channel_id=int(channel_id),
                   auteur=auteur, ends_at=ends_at,
                   duree_s=float(duree_s) if duree_s else None, ping=ping)


class Sondages:
    """Les sondages Discord vivants, indexés par le message qui les porte."""

    def __init__(self) -> None:
        self._par_message: dict[int, Sondage] = {}

    def ajouter(self, sondage: Sondage) -> None:
        self._par_message[sondage.message_id] = sondage

    def par_message(self, message_id: int) -> Optional[Sondage]:
        return self._par_message.get(int(message_id))

    def ouvert_dans(self, channel_id: int) -> Optional[Sondage]:
        """Le sondage encore ouvert d'un salon — celui que « ferme-le » vise."""
        for sondage in self._par_message.values():
            if sondage.channel_id == int(channel_id) and not sondage.clos:
                return sondage
        return None

    def oublier(self, message_id: int) -> None:
        self._par_message.pop(int(message_id), None)

    def ouverts(self) -> list[Sondage]:
        return [s for s in self._par_message.values() if not s.clos]

    def to_dict(self) -> dict[str, Any]:
        return {"sondages": [s.to_dict() for s in self.ouverts()]}

    def from_dict(self, data: Optional[dict[str, Any]]) -> None:
        """Reprend ce qui était en cours. Ne lève JAMAIS : un état abîmé coûte
        un sondage perdu, pas le démarrage du bot."""
        brut = (data or {}).get("sondages")
        if not isinstance(brut, list):
            return
        for item in brut:
            try:
                sondage = Sondage.from_dict(item)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Sondage non repris ({e!r}) : {i!r}", e=exc, i=item)
                continue
            self.ajouter(sondage)
