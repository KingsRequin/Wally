from bot.intelligence.prompts import PromptBuilder


def _builder():
    # PromptBuilder() sans argument (cf. tests/test_weekday_awareness.py) ; build_system_prompt prend tout en kwargs.
    return PromptBuilder()


def test_person_context_rendered_when_present():
    out = _builder().build_system_prompt(
        emotion_state={}, person_context="Azrael, stratège invétéré."
    )
    assert "--- Qui est cette personne ---" in out
    assert "Azrael, stratège invétéré." in out


def test_person_context_absent_when_empty():
    out = _builder().build_system_prompt(emotion_state={})
    assert "Qui est cette personne" not in out
