"""Quand `[SPEAK]` est coupé, le prompt ne doit plus l'enseigner — ni l'exemplifier.

`spontaneous_channel_speak_enabled: false` depuis le 2026-07-14. Le prompt continuait
pourtant à consacrer 408 mots répartis sur dix lignes à expliquer comment et quand
parler spontanément — cinq règles de décision détaillées — et **l'exemple de réponse
publique commençait par `[SPEAK ...]`**. Un exemple pèse lourd pour un modèle.

Le correctif d'alors avait ajouté un paragraphe « Parole spontanée indisponible » à la
fin du système : une contradiction posée après l'enseignement, pas à sa place. On
retire maintenant les passages devenus faux.

Le filtrage repose sur des marqueurs `<!-- SPEAK:début -->` / `<!-- SPEAK:fin -->`
plutôt que sur des motifs de texte : une regex sur la prose aurait cessé de matcher
en silence à la première reformulation du prompt. D'où le premier test, qui vérifie
que les marqueurs sont toujours là.
"""
from pathlib import Path

from bot.intelligence.reasoning_agent import ReasoningAgent

_PROMPTS = Path(__file__).parent.parent / "bot" / "intelligence" / "persona" / "prompts"


def _systeme(speak: bool) -> str:
    return ReasoningAgent(
        llm=None, fact_store=None, prompts_dir=_PROMPTS, spontaneous_speak_enabled=speak
    )._system


def test_les_marqueurs_existent_toujours_dans_le_prompt():
    """Sans eux, le filtrage ne retirerait rien — en silence."""
    brut = (_PROMPTS / "reasoning_system.md").read_text(encoding="utf-8")
    assert brut.count("<!-- SPEAK:début -->") == brut.count("<!-- SPEAK:fin -->")
    assert brut.count("<!-- SPEAK:début -->") >= 3, (
        "les passages SPEAK ne sont plus balisés : le filtrage devient inopérant"
    )


def test_speak_actif_le_prompt_enseigne_lasction():
    sys_actif = _systeme(True)
    assert "[SPEAK" in sys_actif
    assert "APPORTE quelque chose" in sys_actif


def test_speak_coupe_plus_aucune_consigne_ni_exemple():
    """Ce qui doit disparaître : le MODE D'EMPLOI et l'EXEMPLE.

    Deux mentions incidentes subsistent volontairement — « Joie → engage-toi » et
    « préfère TRÈS FORTEMENT `[THINK]` » — parce qu'elles décrivent une inclination,
    pas une procédure, et que le paragraphe de désactivation les recadre juste après.
    Et ce paragraphe doit évidemment pouvoir nommer l'action qu'il désactive.
    """
    sys_coupe = _systeme(False)

    assert "[SPEAK 123456789" not in sys_coupe, "l'exemple montre encore un SPEAK"
    assert "N'émets `[SPEAK]` que si" not in sys_coupe
    # Formulation propre à la règle retirée : « APPORTE quelque chose » seul
    # apparaît aussi dans la directive d'ennui, qui reste (elle offre d'autres
    # issues que la parole — ruminer, se fixer une question).
    assert "Quand tu décides de `[SPEAK]` spontanément" not in sys_coupe
    assert "Ton introspection n'est PAS" not in sys_coupe
    assert "Choix du canal" not in sys_coupe
    assert "le message doit être court" not in sys_coupe

    assert "Parole spontanée indisponible" in sys_coupe
    # Les marqueurs eux-mêmes ne doivent pas fuiter dans le prompt envoyé.
    assert "SPEAK:début" not in sys_coupe


def test_le_reste_du_prompt_survit_au_filtrage():
    """Le filtrage ne doit emporter que les passages balisés."""
    sys_coupe = _systeme(False)
    for garde in ("[THINK]", "create_desire", "advance_goal", "Étanchéité des canaux",
                  "ANCRAGE", "code_fix"):
        assert garde in sys_coupe, f"« {garde} » a disparu avec le filtrage"
