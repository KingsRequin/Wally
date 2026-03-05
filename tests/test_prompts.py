# tests/test_prompts.py
from bot.core.prompts import PromptBuilder


def test_build_includes_base_prompt():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr",
    )
    assert "Tu es Wally." in result


def test_anger_directive_injected_above_threshold():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr",
    )
    # Should contain behavioral directive text for anger, not "tu es en colère"
    assert "impatient" in result.lower() or "court" in result.lower()
    assert "tu es en colère" not in result.lower()


def test_low_emotion_no_directive():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr",
    )
    # Below threshold (0.4), no directives injected — just base + language
    assert "impatient" not in result.lower()


def test_language_directive_french():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr",
    )
    assert "français" in result.lower()


def test_language_directive_english():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="en",
    )
    assert "english" in result.lower()


def test_memory_context_injected():
    pb = PromptBuilder(system_prompt="Tu es Wally.")
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        language="fr",
        memory_context="L'utilisateur s'appelle Alice.",
    )
    assert "Alice" in result


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
        language="fr",
    )
    # All above threshold — only top 2 should be injected
    # Check it doesn't repeat the same directive multiple times
    assert result.count("impatient") <= 1
