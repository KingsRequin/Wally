import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.meta_agent import MetaAgent, MetaDecision, parse_decisions


def test_parse_think():
    decisions = parse_decisions("[THINK]")
    assert len(decisions) == 1
    assert decisions[0].action == "THINK"


def test_parse_speak():
    decisions = parse_decisions('[SPEAK 123456789 "Bonjour tout le monde !"]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "SPEAK"
    assert d.channel_id == "123456789"
    assert d.message == "Bonjour tout le monde !"


def test_parse_speak_french_quotes():
    decisions = parse_decisions('[SPEAK 123456789 «Bonjour tout le monde !»]')
    assert len(decisions) == 1
    assert decisions[0].action == "SPEAK"
    assert decisions[0].channel_id == "123456789"
    assert decisions[0].message == "Bonjour tout le monde !"


def test_parse_speak_curly_quotes():
    decisions = parse_decisions('[SPEAK 42 “salut”]')
    assert decisions[0].action == "SPEAK"
    assert decisions[0].message == "salut"


def test_parse_speak_inner_quotes():
    decisions = parse_decisions('[SPEAK 42 "il a dit "non" hier"]')
    assert decisions[0].action == "SPEAK"
    assert decisions[0].message == 'il a dit "non" hier'


def test_parse_speak_no_quotes():
    decisions = parse_decisions('[SPEAK 42 salut ça va]')
    assert decisions[0].action == "SPEAK"
    assert decisions[0].message == "salut ça va"


def test_parse_speak_with_citation_marker():
    """Régression : une citation `[¹](<url>)` contient un `]` qui coupait le
    message au marqueur (« …facile [¹ »). Le message quoté doit survivre entier."""
    raw = '[SPEAK 42 "Valorant, top ~10% facile [¹](<https://dexerto.com/apex>)"]'
    decisions = parse_decisions(raw)
    speaks = [d for d in decisions if d.action == "SPEAK"]
    assert len(speaks) == 1  # pas de doublon tronqué via le repli
    assert speaks[0].channel_id == "42"
    assert speaks[0].message == "Valorant, top ~10% facile [¹](<https://dexerto.com/apex>)"


def test_parse_speak_alongside_think():
    decisions = parse_decisions('[THINK]\n[SPEAK 99 "coucou"]')
    actions = {d.action for d in decisions}
    assert actions == {"THINK", "SPEAK"}
    speak = next(d for d in decisions if d.action == "SPEAK")
    assert speak.channel_id == "99"
    assert speak.message == "coucou"


def test_parse_act_create_goal():
    decisions = parse_decisions('[ACT create_goal {"description": "Explorer le jazz"}]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "ACT"
    assert d.act_name == "create_goal"
    assert d.act_args == {"description": "Explorer le jazz"}


def test_parse_evolve():
    decisions = parse_decisions('[EVOLVE SOUL "Wally veut être plus spontané"]')
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == "EVOLVE"
    assert d.section == "SOUL"
    assert d.change == "Wally veut être plus spontané"


def test_empty_or_no_tags_defaults_to_think():
    decisions = parse_decisions("Aucun tag ici, juste du texte libre.")
    assert len(decisions) == 1
    assert decisions[0].action == "THINK"
