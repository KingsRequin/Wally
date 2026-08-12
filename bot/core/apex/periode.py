# bot/core/apex/periode.py
"""De quelle fenêtre de temps parle-t-on ?

Un seul parseur, trois consommateurs : l'action `progression`, le panneau
d'overlay et la route qui trace l'image. Chacun calculait sa fenêtre dans son
coin — et une carte pouvait passer la garde du panneau pour une fenêtre que
l'image refusait ensuite de tracer.

Le modèle écrit ici du texte libre (« 5 min », « ce stream », « aujourd'hui ») :
une énumération figée obligeait à demander « live » pour tout, et « la courbe de
ce stream » rendait douze heures glissantes.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bot.core.apex.history import RETENTION_JOURS, _maintenant, debut_de_periode

# Deux relevés sont espacés de 30 s au mieux : sous la minute, une fenêtre ne
# peut rien contenir.
MIN_DUREE_S = 60.0
# L'historique ne remonte pas plus loin : promettre au-delà serait mentir.
MAX_DUREE_S = float(RETENTION_JOURS * 86400)

# Les clés de fenêtre — liste blanche. La route image ne reçoit QUE l'une
# d'elles, jamais un libellé : son titre finit dessiné dans un PNG servi
# publiquement.
CLES = ("stream", "jour", "semaine", "mois", "duree")

_FORMES = "stream, jour, semaine, mois, ou une durée (5m, 30min, 2h, 1h30, 3j)"

_MOTS_STREAM = {"stream", "live", "session", "ce stream", "le stream",
                "ce live", "cette session", "stream en cours"}
_MOTS_NOMMES = {
    "jour": "jour", "aujourdhui": "jour", "journee": "jour", "ce jour": "jour",
    "semaine": "semaine", "cette semaine": "semaine",
    "mois": "mois", "ce mois": "mois", "ce mois-ci": "mois",
}

_UNITES = {
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "heure": 3600, "heures": 3600,
    "j": 86400, "jour": 86400, "jours": 86400,
}
# « 2h », « 45 minutes », « 3 j »
_DUREE = re.compile(r"^(\d+)\s*([a-z]+)$")
# « 1h30 » : la forme parlée, qu'aucune unité seule ne couvre.
_DUREE_HM = re.compile(r"^(\d+)\s*h\s*(\d{1,2})$")


def epoch_depuis_iso(valeur: Any) -> float | None:
    """« 2026-08-12T08:03:00Z » → 1786…, ou None si ce n'est pas une date.

    Twitch date le début d'un live en ISO ; le reste du chemin raisonne en
    timestamps. La conversion vit ici plutôt qu'en `lambda` dans `main.py`, où
    elle serait la seule ligne du fichier à pouvoir lever.
    """
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Fenetre:
    """Le début d'une fenêtre, sa clé de liste blanche, et comment on la dit."""

    depuis: float
    cle: str
    libelle: str


def _normalise(texte: str) -> str:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", (texte or "").strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sans_accents.replace("'", "").split())


def _duree_secondes(texte: str) -> float | None:
    """Le nombre de secondes d'une durée écrite, ou None si ce n'en est pas une."""
    if (hm := _DUREE_HM.match(texte)) is not None:
        return int(hm.group(1)) * 3600 + int(hm.group(2)) * 60
    if (m := _DUREE.match(texte)) is None:
        return None
    unite = _UNITES.get(m.group(2))
    return int(m.group(1)) * unite if unite else None


def libelle_duree(secondes: float) -> str:
    """« sur les 30 dernières minutes ». Sert aussi à retitrer une image dont on
    n'a reçu que l'instant de départ."""
    minutes = int(round(secondes / 60))
    if minutes < 60:
        return f"sur les {minutes} dernières minutes"
    heures = int(round(secondes / 3600))
    if heures < 24:
        return f"sur les {heures} dernières heures"
    jours = int(round(secondes / 86400))
    if jours <= 1:
        return "sur les dernières 24 heures"
    return f"sur les {jours} derniers jours"


_LIBELLES = {
    "stream": "depuis le début du stream",
    "jour": "aujourd'hui",
    "semaine": "cette semaine",
    "mois": "ce mois-ci",
}


def libelle_de(cle: str, depuis: float, *, maintenant: float | None = None) -> str:
    """Le libellé d'une fenêtre reconstruite à partir de sa clé et de son début.

    La route image ne reçoit que ces deux valeurs — un libellé transmis en clair
    serait du texte arbitraire dessiné dans une image publique. Une clé inconnue
    ne rend rien plutôt qu'un titre inventé.
    """
    if cle in _LIBELLES:
        return _LIBELLES[cle]
    if cle == "duree":
        return libelle_duree(max(0.0, (maintenant or _maintenant()) - depuis))
    return ""


def parse_periode(
    texte: str,
    *,
    maintenant: float | None = None,
    debut_stream: float | None = None,
) -> Fenetre:
    """La fenêtre demandée. Lève `ValueError` — jamais de repli silencieux.

    `debut_stream` est résolu par l'appelant (live en cours, sinon dernière
    session de jeu) : ce module ne connaît ni Twitch ni la base.
    """
    now = maintenant or _maintenant()
    mot = _normalise(texte) or "stream"

    if mot in _MOTS_STREAM:
        if debut_stream is None:
            raise ValueError(
                "Je ne sais pas quand ce stream a commencé et je ne vais pas "
                "inventer une fenêtre : demande une période explicite "
                f"({_FORMES})."
            )
        return Fenetre(float(debut_stream), "stream", _LIBELLES["stream"])

    if (cle := _MOTS_NOMMES.get(mot)) is not None:
        return Fenetre(debut_de_periode(cle, maintenant=now), cle, _LIBELLES[cle])

    secondes = _duree_secondes(mot)
    if secondes is None:
        raise ValueError(f"Période incomprise : « {texte} ». Utilise {_FORMES}.")
    if secondes < MIN_DUREE_S:
        raise ValueError(
            "Une fenêtre de moins d'une minute ne peut contenir aucun relevé "
            "(j'en prends un toutes les 30 secondes en live)."
        )
    if secondes > MAX_DUREE_S:
        raise ValueError(
            f"Je ne garde que {RETENTION_JOURS} jours de relevés : au-delà, je "
            "n'ai rien à montrer."
        )
    return Fenetre(now - secondes, "duree", libelle_duree(secondes))
