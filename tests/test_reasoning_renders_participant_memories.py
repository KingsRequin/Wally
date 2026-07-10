from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )
    base.update(kw)
    return AttentionContext(**base)


def _agent():
    agent = ReasoningAgent.__new__(ReasoningAgent)  # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    return agent


def test_format_context_renders_participant_memories():
    text = _agent()._format_context(_ctx(
        participant_memories=[
            {"author": "Pierre", "facts": ["aime le jazz", "vit à Lyon"]},
        ],
    ))
    assert "Pierre" in text
    assert "aime le jazz" in text
    assert "vit à Lyon" in text


def test_format_context_no_participant_block_when_empty():
    text = _agent()._format_context(_ctx(participant_memories=[]))
    assert "personnes présentes" not in text.lower()


def test_format_context_renders_participant_mention_id():
    # L'id de ping est accolé au nom, et la consigne d'usage est présente.
    text = _agent()._format_context(_ctx(
        participant_memories=[
            {"author": "Cluth", "mention": "<@973>", "facts": ["joue à Apex"]},
        ],
    ))
    assert "Cluth (<@973>)" in text
    assert "identifiant de ping" in text
    assert "notifi" in text.lower()


def test_format_context_participant_without_mention_falls_back_to_name():
    # Twitch ou id absent → on affiche juste le nom, sans parenthèses vides.
    text = _agent()._format_context(_ctx(
        participant_memories=[
            {"author": "keychka", "mention": "", "facts": ["stream le soir"]},
        ],
    ))
    assert "keychka : stream le soir" in text
    assert "keychka ()" not in text
