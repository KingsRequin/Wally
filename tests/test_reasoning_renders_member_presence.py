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


def test_format_context_renders_member_presence():
    text = _agent()._format_context(_ctx(
        member_presence=[
            "Az est ne pas déranger — joue à Apex.",
            "Bob est inactif.",
        ],
    ))
    assert "Qui est là en ce moment" in text
    assert "Az est ne pas déranger — joue à Apex." in text
    assert "Bob est inactif." in text
    # Consigne comportementale présente pour orienter la décision.
    assert "ne dérange pas" in text.lower()


def test_format_context_no_presence_block_when_empty():
    text = _agent()._format_context(_ctx(member_presence=[]))
    assert "qui est là en ce moment" not in text.lower()
