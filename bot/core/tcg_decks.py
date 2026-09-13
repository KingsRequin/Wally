"""Les decks Wallycard : ce qu'un deck a le droit de contenir.

Sans base et sans réseau : la route range, ce module juge. C'est ici que vivent
les limites du jeu, parce que le serveur est le seul endroit où elles ne se
contournent pas — le front les applique pour l'affichage, mais une limite tenue
par le client seul tombe au premier `curl`.

Règles arrêtées par l'owner le 2026-09-13 (spec
`docs/superpowers/specs/2026-09-13-wallycard-site-design.md`) :

- 15 cartes tactiques et 3 héros ;
- UN SEUL exemplaire par carte ;
- un deck INCOMPLET s'enregistre. Aucun héros n'est prêt aujourd'hui : refuser
  les brouillons rendrait l'éditeur inutilisable, personne ne sauvegarderait rien.
"""

from __future__ import annotations

from bot.core.tcg_cartes import CARTES
from bot.core.tcg_cartes_action import CARTES_ACTION

TAILLE_DECK = 15
HEROS_PAR_DECK = 3
NOM_MAX = 40
# Un plafond par compte, pour qu'une boucle côté client ne remplisse pas la
# base. Assez large pour ne jamais gêner un vrai joueur.
DECKS_PAR_COMPTE = 30


class DeckInvalide(ValueError):
    """Un deck refusé. Le message part tel quel jusqu'à l'éditeur : il doit se
    lire par un joueur, pas par un développeur."""


def _sans_doublon(cles: list[str], quoi: str) -> None:
    vus: set[str] = set()
    for cle in cles:
        if cle in vus:
            raise DeckInvalide(f"{quoi} en double : un seul exemplaire par deck.")
        vus.add(cle)


def valider(nom: str, heros: list[str], cartes: list[str]) -> str:
    """Refuse un deck qui enfreint les règles, et rend son nom nettoyé.

    ⚠️ La vérification de l'existence passe par les deux catalogues SÉPARÉS :
    un héros posé dans les cartes tactiques est une clé connue, mais pas une
    carte tactique.
    """
    nom = nom.strip()
    if not nom:
        raise DeckInvalide("Le deck doit avoir un nom.")
    if len(nom) > NOM_MAX:
        raise DeckInvalide(f"Le nom du deck ne peut pas dépasser {NOM_MAX} caractères.")

    if len(heros) > HEROS_PAR_DECK:
        raise DeckInvalide(f"Un deck compte au plus {HEROS_PAR_DECK} héros.")
    _sans_doublon(heros, "Héros")
    inconnus = [cle for cle in heros if cle not in CARTES]
    if inconnus:
        raise DeckInvalide(f"Héros inconnu : {inconnus[0]}.")

    if len(cartes) > TAILLE_DECK:
        raise DeckInvalide(f"Un deck compte au plus {TAILLE_DECK} cartes.")
    _sans_doublon(cartes, "Carte")
    inconnues = [cle for cle in cartes if cle not in CARTES_ACTION]
    if inconnues:
        raise DeckInvalide(f"Carte inconnue : {inconnues[0]}.")

    return nom


def complet(heros: list[str], cartes: list[str]) -> bool:
    """Un deck jouable. DÉDUIT, jamais stocké : un drapeau rangé en base
    mentirait le jour où une carte sort du catalogue."""
    return len(heros) == HEROS_PAR_DECK and len(cartes) == TAILLE_DECK
