"""Quand la parole spontanée est coupée, SPEAK ne doit plus être proposé au LLM.

Mesuré en prod : le décideur choisissait SPEAK et rédigeait le message, jeté
ensuite au dispatch (18 fois en 5 jours). Il décidait en boucle une action
structurellement impossible.
"""
from pathlib import Path

from bot.intelligence.reasoning_agent import ReasoningAgent

_PROMPTS = Path("bot/intelligence/persona/prompts")


def _agent(enabled: bool) -> ReasoningAgent:
    return ReasoningAgent(None, None, _PROMPTS, spontaneous_speak_enabled=enabled)


def test_speak_reste_disponible_par_defaut():
    assert "Parole spontanée indisponible" not in _agent(True)._system


def test_directive_ajoutee_quand_speak_est_coupe():
    system = _agent(False)._system
    assert "Parole spontanée indisponible" in system
    assert "N'en émets aucun" in system


def test_le_prompt_de_base_est_conserve():
    """La directive s'ajoute, elle ne remplace pas les consignes existantes."""
    base, bride = _agent(True)._system, _agent(False)._system
    assert bride.startswith(base)
    assert len(bride) > len(base)
