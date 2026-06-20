import pytest
from unittest.mock import AsyncMock, MagicMock
from wally_v2.core.meta_agent import MetaAgent, MetaDecision, parse_decisions


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
