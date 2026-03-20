# tests/test_emoji_reactions.py
import re

import pytest


# ── Parse react tag ───────────────────────────────────────────────────────

def test_parse_react_tag_extracts_emoji():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:😂] c'est drôle")
    assert emoji == "😂"
    assert text == "c'est drôle"


def test_parse_react_tag_no_tag():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("texte normal")
    assert emoji is None
    assert text == "texte normal"


def test_parse_react_tag_strips_whitespace():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:🔥]  texte avec espaces")
    assert emoji == "🔥"
    assert text == "texte avec espaces"


def test_parse_react_tag_skull():
    from bot.discord.handlers import _parse_react_tag
    emoji, text = _parse_react_tag("[react:💀] mort de rire")
    assert emoji == "💀"
    assert text == "mort de rire"


# ── Passive reaction rules ────────────────────────────────────────────────

def test_passive_reaction_matches_laugh_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("mdr c'est trop drôle", curiosity=0.0)
    assert emoji in ("😂", "💀")


def test_passive_reaction_matches_positive_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("gg bravo c'était propre", curiosity=0.0)
    assert emoji in ("🔥", "👏")


def test_passive_reaction_matches_negative_keywords():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("putain c'est nul", curiosity=0.0)
    assert emoji in ("😤", "💀")


def test_passive_reaction_matches_curiosity_question():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("comment ça marche exactement ?", curiosity=0.5)
    assert emoji == "🤔"


def test_passive_reaction_no_signal_returns_none():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("je vais au magasin", curiosity=0.0)
    assert emoji is None


def test_passive_reaction_curiosity_below_threshold():
    from bot.discord.handlers import _pick_passive_emoji
    emoji = _pick_passive_emoji("c'est quoi ?", curiosity=0.2)
    assert emoji is None  # curiosity < 0.4
