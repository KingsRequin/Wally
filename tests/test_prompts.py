# tests/test_prompts.py
from bot.core.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}


def test_build_includes_base_prompt():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    assert "Tu es Wally." in result


def test_anger_directive_injected_above_threshold():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
    )
    assert "impatient" in result.lower() or "court" in result.lower()
    assert "tu es en colère" not in result.lower()


def test_low_emotion_no_directive():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
    )
    assert "impatient" not in result.lower()


def test_language_directive_adaptive():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(emotion_state=_EMOTIONS_FLAT)
    # Should instruct the bot to adapt to the user's language
    assert "langue" in result.lower()
    assert "utilisateur" in result.lower()


def test_memory_context_injected():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        memory_context="L'utilisateur s'appelle Alice.",
    )
    assert "Alice" in result


def test_situation_context_injected():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Discord", "server": "MonServeur", "channel": "#général"},
    )
    assert "Discord" in result
    assert "MonServeur" in result
    assert "#général" in result


def test_situation_twitch():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Twitch", "streamer": "wallytebully", "channel": "#wallytebully"},
    )
    assert "Twitch" in result
    assert "wallytebully" in result


def test_build_context_block_with_messages():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    messages = [
        {"author": "Alice", "content": "Bonjour !", "timestamp": 1000.0},
        {"author": "Bob", "content": "Salut !", "timestamp": 1001.0},
    ]
    block = pb.build_context_block(messages)
    assert "[Alice]: Bonjour !" in block
    assert "[Bob]: Salut !" in block


def test_build_context_block_empty():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    assert pb.build_context_block([]) == ""


def test_format_event_message():
    result = PromptBuilder.format_event_message(
        "Bienvenue {username} ! Tu as donné {amount} bits.",
        username="Alice",
        amount=100,
        months=0,
        raiders_count=0,
    )
    assert result == "Bienvenue Alice ! Tu as donné 100 bits."


def test_at_most_two_dominant_emotions():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.8, "sadness": 0.7, "curiosity": 0.6, "boredom": 0.5},
    )
    assert result.count("impatient") <= 1


# ── build_prelude_block ───────────────────────────────────────────────────────

def test_build_prelude_block_empty():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    assert pb.build_prelude_block([]) == ""


def test_build_prelude_block_formats_messages():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    messages = [
        {"author": "Alice", "content": "Salut tout le monde", "timestamp": 1.0},
        {"author": "Bob", "content": "Ça roule ?", "timestamp": 2.0},
    ]
    result = pb.build_prelude_block(messages)
    assert "[Alice]: Salut tout le monde" in result
    assert "[Bob]: Ça roule ?" in result
    assert result != ""
