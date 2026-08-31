"""Le catalogue de rébus en emoji : chargement, tirage, indices, réponse.

Aucun LLM ici, et c'est le point. Un rébus phonétique demande une décomposition
en sons du français ; les modèles s'y cassent les dents et personne ne voit
passer un rébus insoluble avant le chat. Les 226 énigmes sont donc ÉCRITES, dans
`bot/persona/rebus.json` — bind-monté, donc l'owner en ajoute une pendant le live
sans rebuild.

Le fichier porte sa propre convention (deux lectures admises, le SON ou
l'ORTHOGRAPHE) et les six pièges qui ont coûté 48 entrées à la relecture. Il se
lit avant d'y toucher.

`lecture[i]` est ce que `emojis[i]` doit se prononcer. C'est ce qui rend le
catalogue vérifiable à l'œil ET ce qui fournit les indices progressifs : on
n'écrit pas les indices à la main, on les DÉRIVE. Un rébus ajouté au fichier
arrive donc avec les siens, sans une ligne de plus.
"""
from __future__ import annotations

import json
import random
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

CHEMIN_DEFAUT = Path(__file__).resolve().parents[1] / "persona" / "rebus.json"

# Les jetons se joignent par une ESPACE, jamais par concaténation nue : deux
# indicateurs régionaux voisins fusionneraient en drapeau de pays. Le fichier
# n'en contient plus un seul (les lettres y sont des caractères ordinaires),
# mais le séparateur reste la ceinture — il ne coûte rien et le piège avait
# rendu 70 entrées illisibles.
SEPARATEUR = " "


@dataclass(frozen=True)
class Rebus:
    """Une énigme du catalogue. Immuable : le tirage la partage, personne ne l'édite."""

    mot: str
    emojis: tuple[str, ...]
    lecture: tuple[str, ...]
    categorie: str

    @property
    def enigme(self) -> str:
        """La ligne qui part dans le chat. Les emoji, rien d'autre."""
        return SEPARATEUR.join(self.emojis)

    @property
    def solution(self) -> str:
        """« chat + eau » — la décomposition, pour la révélation."""
        return " + ".join(self.lecture)


def charger(chemin: Path | None = None) -> list[Rebus]:
    """Lit le catalogue. Rend une liste VIDE si le fichier manque ou ment.

    Un catalogue absent n'est pas une raison de tuer le bot : la commande se
    taira, et le log dira pourquoi. En revanche il le dit en WARNING — un DEBUG
    n'existe pas en prod, et le jeu serait muet sans que rien ne l'explique.
    """
    chemin = chemin or CHEMIN_DEFAUT
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        entrees = brut["rebus"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Rébus : catalogue illisible ({p}) : {e!r}", p=chemin, e=exc)
        return []

    out: list[Rebus] = []
    for e in entrees:
        try:
            emojis, lecture = tuple(e["emojis"]), tuple(e["lecture"])
            if not emojis or len(emojis) != len(lecture):
                # L'invariant du fichier : un jeton, une lecture. Une entrée
                # bancale donnerait des indices décalés — on la saute PLUTÔT
                # que de la jouer de travers, et on la nomme.
                logger.warning("Rébus « {m} » ignoré : jetons et lectures désaccordés",
                               m=e.get("mot", "?"))
                continue
            out.append(Rebus(str(e["mot"]), emojis, lecture, str(e["categorie"])))
        except (KeyError, TypeError) as exc:
            logger.warning("Rébus ignoré, entrée incomplète : {e!r}", e=exc)
    logger.info("Rébus : {n} énigmes chargées depuis {p}", n=len(out), p=chemin.name)
    return out


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, sans ponctuation — pour comparer des réponses.

    « Château ! », « chateau » et « CHÂTEAU » sont la même réponse. Refuser la
    deuxième parce qu'il manque un accent circonflexe, dans un chat Twitch,
    serait perdre un gagnant sur deux.
    """
    plat = unicodedata.normalize("NFD", texte.lower())
    plat = "".join(c for c in plat if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plat).strip()


def trouve(rebus: Rebus, message: str) -> bool:
    """Ce message contient-il la réponse ?

    On cherche le mot DANS la phrase, pas la phrase entière : personne ne tape
    « chameau » tout seul, on tape « c'est un chameau non ? ». Mais on le cherche
    sur ses BORDS — sans quoi « château » validerait « chat », et le jeu se
    gagnerait tout seul à la première ligne venue.

    Le pluriel passe, en -s ET en -x : le catalogue est plein de mots en -eau,
    dont le pluriel est « chameaux ». N'accepter que le -s aurait refusé la
    bonne réponse à qui l'écrit correctement, sur trente entrées.
    """
    attendu = normaliser(rebus.mot)
    if not attendu:
        return False
    return bool(re.search(rf"\b{re.escape(attendu)}[sx]?\b", normaliser(message)))


def indices(rebus: Rebus) -> list[str]:
    """Les indices, du plus vague au plus parlant. Dérivés, jamais écrits.

    Le DERNIER jeton n'est jamais donné : un indice qui livre la réponse n'est
    pas un indice, c'est la fin de la partie. Il reste donc toujours un pas à
    faire, y compris après le dernier indice.
    """
    lettres = len(normaliser(rebus.mot).replace(" ", ""))
    out = [
        f"c'est dans la catégorie « {rebus.categorie} »",
        f"le mot fait {lettres} lettres",
    ]
    out += [f"le {n}{'er' if n == 1 else 'e'} dessin se lit « {lu} »"
            for n, lu in enumerate(rebus.lecture[:-1], 1)]
    return out


class Sac:
    """Tirage SANS REMISE : le catalogue s'épuise avant de se rejouer.

    Avec remise, sur 226 énigmes et quelques parties par live, le hasard
    ramènerait le même rébus deux soirs de suite et ça se verrait tout de suite.
    Le sac se recharge quand il est vide.
    """

    def __init__(self, rebus: list[Rebus], alea: random.Random | None = None) -> None:
        self._tous = list(rebus)
        self._restants: list[Rebus] = []
        self._alea = alea or random.Random()

    def tirer(self) -> Rebus | None:
        """Le prochain rébus, ou None si le catalogue est vide."""
        if not self._restants:
            self._restants = list(self._tous)
            self._alea.shuffle(self._restants)
        return self._restants.pop() if self._restants else None
