from bot.intelligence.attention_agent import AttentionContext
from bot.intelligence.reasoning_agent import ReasoningAgent


def _ctx(**kw):
    base = dict(
        emotion_state={"boredom": 0.1}, active_desires=[], active_goals=[],
        recent_thoughts=[], recent_interactions=[], time_of_day="night",
    )
    base.update(kw)
    return AttentionContext(**base)


def test_format_context_includes_receptivity():
    agent = ReasoningAgent.__new__(ReasoningAgent)   # pas d'I/O constructeur
    agent._channels_text = ""
    agent._capabilities_text = ""
    agent._channel_names = {}
    text = agent._format_context(_ctx(
        social_receptivity="Il est 3h en semaine : le serveur est très calme.",
    ))
    assert "le serveur est très calme" in text
