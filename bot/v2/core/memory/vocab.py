# bot/v2/core/memory/vocab.py
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

from bot.v2.core.memory.facts import FactCategory

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


def is_valid_predicate(predicate: str) -> bool:
    return predicate in PREDICATES


def is_valid_category(category: str) -> bool:
    return category in CATEGORIES
