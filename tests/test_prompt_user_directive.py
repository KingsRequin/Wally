# tests/test_prompt_user_directive.py
from bot.intelligence.prompts import PromptBuilder

_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_FURAX = {"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}
_DIRECTIVES = {
    "anger_high": "Tu es furax, cinglant, et tu n'hésites pas à insulter.",
    "anger_mid": "Tes réponses sont courtes et impatientes.",
    "joy_high": "Tu es euphorique.",
}
_LOVE = "Tu es éperdument amoureux de cette personne. Tu glisses des cœurs."


def test_user_directive_injected():
    pb = PromptBuilder()
    result = pb.build_system_prompt(emotion_state=_FLAT, user_directive=_LOVE)
    assert "éperdument amoureux" in result
    assert "--- Directive comportementale ---" in result


def test_user_directive_shortcircuits_anger():
    """Le cœur de la feature : la colère ne doit PAS contredire la directive."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FURAX,
        emotion_directives=_DIRECTIVES,
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "furax" not in result.lower()
    assert "cinglant" not in result.lower()


def test_user_directive_shortcircuits_secondaries():
    """Les émotions secondaires sont prioritaires sur tout SAUF la directive utilisateur."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FLAT,
        secondary_directives={"frustration_high": "Tu es frustré et hargneux."},
        active_secondaries=[("frustration", 0.9)],
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "hargneux" not in result.lower()


def test_user_directive_shortcircuits_composites():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.6, "joy": 0.5, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_DIRECTIVES,
        composite_directives={"anger_joy": "Tu ris jaune, tu es acide."},
        user_directive=_LOVE,
    )
    assert "éperdument amoureux" in result
    assert "acide" not in result.lower()


def test_single_behavioral_header():
    """Un seul slot « Directive comportementale » — pas deux consignes concurrentes."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FURAX,
        emotion_directives=_DIRECTIVES,
        secondary_directives={"frustration_high": "Tu es frustré."},
        active_secondaries=[("frustration", 0.9)],
        user_directive=_LOVE,
    )
    assert result.count("--- Directive comportementale ---") == 1


def test_no_user_directive_keeps_emotion_chain():
    """Non-régression : sans directive utilisateur, la colère s'exprime normalement."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(emotion_state=_FURAX, emotion_directives=_DIRECTIVES)
    assert "furax" in result.lower()


def test_user_directive_is_dynamic_not_static():
    """La directive doit rester APRÈS la persona : le préfixe cachable DeepSeek
    couvre le statique, et un contenu par-utilisateur l'invaliderait."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_FLAT,
        persona_block="TU_ES_WALLY",
        user_directive=_LOVE,
    )
    assert result.index("TU_ES_WALLY") < result.index("éperdument amoureux")
