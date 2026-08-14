"""Quand la parole spontanée est coupée, SPEAK ne doit plus être proposé au LLM.

Mesuré en prod : le décideur choisissait SPEAK et rédigeait le message, jeté
ensuite au dispatch (18 fois en 5 jours). Il décidait en boucle une action
structurellement impossible.

⚠️ Ces tests EXIGEAIENT en partie le défaut du 2026-08-13 : ils épinglaient le
titre « Parole spontanée indisponible » et une consigne qui n'énonçait que
l'interdiction. Wally en concluait qu'il était aphone — 19 pensées sur 145 ce
jour-là affirment « je ne peux pas écrire dans le chat en ce moment », pendant
qu'il répondait à trois personnes toutes les vingt secondes. Ils vérifient
désormais le contraire : la consigne doit d'abord dire ce qui RESTE possible.
"""
from pathlib import Path

from bot.intelligence.reasoning_agent import SPEAK_COUPE, ReasoningAgent

_PROMPTS = Path("bot/intelligence/persona/prompts")


def _agent(enabled: bool) -> ReasoningAgent:
    return ReasoningAgent(None, None, _PROMPTS, spontaneous_speak_enabled=enabled)


def test_speak_reste_disponible_par_defaut():
    assert SPEAK_COUPE not in _agent(True)._system


def test_directive_ajoutee_quand_speak_est_coupe():
    system = _agent(False)._system
    assert SPEAK_COUPE in system
    assert "N'en émets aucun" in system


def test_la_consigne_dit_dabord_ce_qui_reste_possible():
    """Une capacité coupée se dit en nommant ce qui marche encore."""
    consigne = SPEAK_COUPE
    assert "PAS muet" in consigne
    for reste in ("mention", "chat Twitch", "DM", "vocal"):
        assert reste in consigne, (
            f"la consigne ne dit pas qu'il répond encore sur « {reste} » :\n{consigne}"
        )
    # Ce qui reste possible doit venir AVANT l'interdiction, pas en rattrapage.
    assert consigne.index("PAS muet") < consigne.index("Ce qui est coupé")


def test_la_consigne_ne_peut_plus_se_lire_comme_un_mutisme():
    """Les formulations qui ont produit les 19 pensées « je suis aphone »."""
    consigne = SPEAK_COUPE
    assert "Parole spontanée indisponible" not in consigne
    assert "ne rédige pas de message destiné à un canal" not in consigne
    assert "est actuellement désactivée" not in consigne


def test_la_consigne_interdit_de_se_declarer_muet():
    """Le symptôme se disait dans la PENSÉE : il faut le nommer là."""
    assert "ce serait faux" in SPEAK_COUPE
    assert "ta pensée" in SPEAK_COUPE


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
