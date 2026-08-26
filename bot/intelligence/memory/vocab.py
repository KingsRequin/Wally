# bot/intelligence/memory/vocab.py
"""Vocabulaire fermé pour les faits mémoire — porté/adapté de jarvis-OS.

Un fait est un triplet sujet-prédicat-objet + catégorie. Le prédicat et la
catégorie sont contraints à ces ensembles fermés ; tout terme hors vocabulaire
fait passer le fait en `needs_review` à l'ingestion (il n'entre pas en base
principale). Cela garde la mémoire structurée et déduplicable.

Les catégories réutilisent l'enum `FactCategory` existant (le gate en dépend :
REL/EMOTION/DESIRE). Les prédicats sont adaptés à l'univers social de Wally
(Discord/Twitch) plutôt qu'à l'assistant personnel de jarvis.
"""
from __future__ import annotations

from bot.intelligence.memory.facts import FactCategory

# Prédicats fermés — imposés à l'extracteur de faits.
PREDICATES: frozenset[str] = frozenset(
    {
        "is",            # identité, attributs ("X is développeur")
        "has",           # possession ("X has un chat")
        "prefers",       # préférence positive
        "dislikes",      # préférence négative
        "plays",         # jeux ("X plays Apex")
        "uses",          # outils/logiciels
        "wants",         # désir/objectif
        "plans",         # intention future
        "believes",      # opinion/croyance
        "needs",         # besoin
        "feels",         # état émotionnel rapporté
        "values",        # valeur profonde
        "speaks",        # langue habituelle
        "knows",         # connaissance/relation à une entité
        "relates_to",    # relation sociale ("X relates_to Y : ami")
    }
)

# Catégories fermées — l'enum FactCategory existant fait foi (compat gate).
CATEGORIES: frozenset[str] = frozenset(c.value for c in FactCategory)


# Tournure française de chaque prédicat, pour le texte LISIBLE d'un fait.
#
# Le prédicat reste anglais en base : la colonne `predicate` est la clé sur
# laquelle la réconciliation compare les faits, et un ensemble fermé stable vaut
# mieux qu'une conjugaison. Mais `content` part au prompt que Wally lit sur les
# gens, et il y lisait « polylrose has piscine », « mks_zedd plays Apex Legends ».
_PREDICATE_FR: dict[str, str] = {
    "is":         "est",
    "has":        "a",
    "prefers":    "préfère",
    "dislikes":   "n'aime pas",
    "plays":      "joue à",
    "uses":       "utilise",
    "wants":      "veut",
    "plans":      "prévoit de",
    "believes":   "pense que",
    "needs":      "a besoin de",
    "feels":      "ressent",
    "values":     "tient à",
    "speaks":     "parle",
    "knows":      "connaît",
    "relates_to": "est lié à",
}


# Seul `is` peut être escamoté quand l'objet porte déjà son propre verbe. Les
# autres prédicats portent le sens du fait (`joue à`, `utilise`, `connaît`…) et
# ne s'effacent jamais. `has` non plus : son « a » forme un passé composé
# parfaitement correct — « polylrose a fait un métier stressant » ; l'escamoter
# donnerait un présent, donc un autre sens.
_VERBES_DE_LIAISON = frozenset({"is"})

# Verbes conjugués à la 3e personne qu'on retrouve en tête d'objet quand le
# modèle a choisi `is` faute de mieux : « is va bien », « is mange sur le sol ».
# Liste volontairement courte et fréquentielle — mieux vaut laisser passer un cas
# rare que d'escamoter le verbe d'un attribut légitime.
_OBJET_DEJA_CONJUGUE = frozenset(
    """arrive attend cherche commence connaît continue demande dit donne essaie
    fait joue laisse met mange parle part passe pense prend prépare regarde
    reste revient sait suit teste travaille trouve va veut vient vit""".split()
)


def render_triplet(subject: str, predicate: str, object_: str) -> str:
    """Phrase lisible d'un triplet S-P-O, prédicat traduit.

    Un prédicat hors vocabulaire est laissé tel quel : une phrase imparfaite
    vaut mieux qu'un fait vide.

    Le verbe de liaison saute quand l'objet est déjà une action conjuguée. Le
    modèle choisit parfois `is` faute de prédicat qui colle — « kingsrequin is
    va bien », « polylrose is mange sur le sol » — et traduire mécaniquement
    donnerait « kingsrequin est va bien ».
    """
    pred = (predicate or "").strip()
    sujet = (subject or "").strip()
    objet = (object_ or "").strip()

    verbe = _PREDICATE_FR.get(pred, pred)
    if pred in _VERBES_DE_LIAISON and objet:
        premier = objet.split(maxsplit=1)[0].casefold().strip(".,;:!?")
        if premier in _OBJET_DEJA_CONJUGUE:
            verbe = ""

    return " ".join(p for p in (sujet, verbe, objet) if p).strip()


