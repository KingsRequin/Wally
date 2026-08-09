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
    """La directive ne doit pas emporter les consignes SANS RAPPORT avec la parole.

    L'assertion d'origine était `bride.startswith(base)` : la directive s'ajoutait en
    fin de prompt sans rien retirer. Depuis le 2026-08-09, les passages qui
    ENSEIGNENT `[SPEAK]` sont au contraire retirés — un mode d'emploi suivi d'une
    interdiction, plus un exemple qui montrait un `[SPEAK]`, contredisaient la
    directive au lieu de la servir (cf. tests/test_reasoning_speak_sections.py).
    Ce test garde donc son intention — ne pas écraser le reste — sans son moyen.
    """
    bride = _agent(False)._system
    for garde in ("ANCRAGE", "[THINK]", "create_desire", "advance_goal", "code_fix",
                  "Étanchéité des canaux", "EVOLVE"):
        assert garde in bride, f"« {garde} » a disparu du prompt bridé"
