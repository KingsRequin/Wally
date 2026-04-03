# tests/test_prompts.py
from bot.core.prompts import PromptBuilder

_EMOTIONS_FLAT = {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0}

_EMOTION_DIRECTIVES = {
    "anger_low": "Tu es légèrement sec et expéditif.",
    "anger_mid": "Tes réponses sont courtes et impatientes. Tu réponds sec, sans fioritures.",
    "anger_high": "Tu es furax, cinglant, et tu n'hésites pas à insulter.",
    "joy_low": "Tu es un peu plus léger que d'habitude.",
    "joy_mid": "Tu es enthousiaste et chaleureux. Tes réponses sont vivantes.",
    "joy_high": "Tu es euphorique, tu déborde d'énergie positive.",
    "sadness_low": "Tu es un peu mélancolique, un peu distant.",
    "sadness_mid": "Tu es mélancolique et introspectif.",
    "sadness_high": "Tu es profondément triste, presque abattu.",
    "curiosity_low": "Tu es légèrement intrigué.",
    "curiosity_mid": "Tu es particulièrement curieux et poseur de questions.",
    "curiosity_high": "Tu es complètement absorbé par le sujet, passionné.",
    "boredom_low": "Tu sembles un peu distrait.",
    "boredom_mid": "Tu sembles peu enthousiaste.",
    "boredom_high": "Tu décroches totalement, réponses minimales.",
}


def test_build_includes_persona_block():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        persona_block="Tu es Wally.",
    )
    assert "Tu es Wally." in result


def test_anger_high_directive_injected():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "furax" in result.lower()


def test_low_emotion_no_directive():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "impatient" not in result.lower()


def test_language_directive_in_persona_block():
    pb = PromptBuilder()
    # La directive de langue vient du persona_block (SOUL.md) — pas injectée séparément
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        persona_block="Tu parles toujours dans la langue de ton interlocuteur. Si quelqu'un t'écrit en anglais, tu réponds en anglais.",
    )
    assert "langue" in result.lower()
    assert "anglais" in result.lower()


def test_memory_context_injected():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        memory_context="L'utilisateur s'appelle Alice.",
    )
    assert "Alice" in result


def test_situation_context_injected():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Discord", "server": "MonServeur", "channel": "#général"},
    )
    assert "Discord" in result
    assert "MonServeur" in result
    assert "#général" in result


def test_situation_twitch():
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        situation={"platform": "Twitch", "streamer": "wallytebully", "channel": "#wallytebully"},
    )
    assert "Twitch" in result
    assert "wallytebully" in result


def test_build_context_block_with_messages():
    pb = PromptBuilder()
    messages = [
        {"author": "Alice", "content": "Bonjour !", "timestamp": 1000.0},
        {"author": "Bob", "content": "Salut !", "timestamp": 1001.0},
    ]
    block = pb.build_context_block(messages)
    assert "[Alice]: Bonjour !" in block
    assert "[Bob]: Salut !" in block


def test_build_context_block_empty():
    pb = PromptBuilder()
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
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.8, "sadness": 0.7, "curiosity": 0.6, "boredom": 0.5},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "furax" in result.lower()
    assert "euphorique" in result.lower()
    assert "abattu" not in result.lower()


def test_no_emotion_directives_when_not_passed():
    pb = PromptBuilder()
    # Sans emotion_directives → aucune directive comportementale injectée
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.9, "joy": 0.8, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
    )
    assert "impatient" not in result.lower()
    assert "Directive comportementale" not in result


# ── build_prelude_block ───────────────────────────────────────────────────────

def test_build_prelude_block_empty():
    pb = PromptBuilder()
    assert pb.build_prelude_block([]) == ""


def test_build_prelude_block_formats_messages():
    pb = PromptBuilder()
    messages = [
        {"author": "Alice", "content": "Salut tout le monde", "timestamp": 1.0},
        {"author": "Bob", "content": "Ça roule ?", "timestamp": 2.0},
    ]
    result = pb.build_prelude_block(messages)
    assert "[Alice]: Salut tout le monde" in result
    assert "[Bob]: Ça roule ?" in result
    assert result != ""


# ── Tiered directive tests ────────────────────────────────────────────────────

def test_tiered_directive_low():
    """anger=0.3 → injecte anger_low."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.3, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "expéditif" in result.lower()
    assert "furax" not in result.lower()


def test_tiered_directive_mid():
    """anger=0.5 → injecte anger_mid."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "impatient" in result.lower()
    assert "furax" not in result.lower()


def test_tiered_directive_high():
    """anger=0.8 → injecte anger_high."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.8, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "furax" in result.lower()


def test_no_directive_below_02():
    """anger=0.1 → aucune directive."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.1, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "Directive comportementale" not in result


def test_top2_with_different_tiers():
    """joy=0.8 (high) + curiosity=0.3 (low) → les deux injectées avec le bon palier."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.0, "joy": 0.8, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0},
        emotion_directives=_EMOTION_DIRECTIVES,
    )
    assert "euphorique" in result.lower()
    assert "intrigué" in result.lower()


def test_missing_tiered_key_silently_skipped():
    """Si une clé tiered manque dans les directives, pas d'erreur."""
    pb = PromptBuilder()
    partial = {"anger_low": "sec", "anger_high": "furax"}
    result = pb.build_system_prompt(
        emotion_state={"anger": 0.5, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        emotion_directives=partial,
    )
    assert "sec" not in result
    assert "furax" not in result


def test_get_tier_returns_correct_level():
    from bot.core.prompts import _get_tier
    assert _get_tier(0.0) is None
    assert _get_tier(0.1) is None
    assert _get_tier(0.19) is None
    assert _get_tier(0.2) == "low"
    assert _get_tier(0.3) == "low"
    assert _get_tier(0.39) == "low"
    assert _get_tier(0.4) == "mid"
    assert _get_tier(0.5) == "mid"
    assert _get_tier(0.69) == "mid"
    assert _get_tier(0.7) == "high"
    assert _get_tier(0.8) == "high"
    assert _get_tier(1.0) == "high"


def test_memory_recall_directive_injected():
    """When memory_context is present, the recall directive is injected."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        memory_context="Aime le Python et joue à Apex.",
    )
    assert "Ce que tu sais de cet utilisateur" in result
    assert "souvenir" in result.lower() or "rappelle" in result.lower()


def test_memory_recall_directive_absent_when_no_memory():
    """When memory_context is empty, no recall directive is injected."""
    pb = PromptBuilder()
    result = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
    )
    assert "ça me rappelle" not in result.lower()
    assert "souvenir" not in result.lower()


def test_build_system_prompt_includes_graph_context():
    """graph_context should appear in the system prompt when provided."""
    pb = PromptBuilder()
    prompt = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        graph_context="--- Connaissances du graphe ---\n- Alice joue à Apex",
    )
    assert "Connaissances du graphe" in prompt
    assert "Alice joue à Apex" in prompt


def test_build_system_prompt_omits_empty_graph_context():
    """Empty graph_context should not add anything to the prompt."""
    pb = PromptBuilder()
    prompt = pb.build_system_prompt(
        emotion_state=_EMOTIONS_FLAT,
        graph_context="",
    )
    assert "Connaissances du graphe" not in prompt


def test_social_context_injected():
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(
        emotion_state={"joy": 0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1},
        social_context="--- Relations sociales connues ---\n• Keychka ↔ Azrael  (très proches)",
    )
    assert "Relations sociales connues" in prompt
    assert "Keychka ↔ Azrael" in prompt


def test_social_context_empty_not_injected():
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(
        emotion_state={"joy": 0.5, "anger": 0.0, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.1},
        social_context="",
    )
    assert "Relations sociales" not in prompt
