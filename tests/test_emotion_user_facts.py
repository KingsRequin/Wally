from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.emotion import EmotionEngine

@pytest.fixture
def engine():
    config = MagicMock()
    config.emotions = {}
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    db = AsyncMock()
    e = EmotionEngine(config, db=db)
    openai = AsyncMock()
    e.set_openai_client(openai)
    return e

@pytest.mark.asyncio
async def test_process_message_returns_user_facts(engine):
    engine._openai.complete_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.1, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.02,
        "love_delta": 0.01,
        "user_facts": ["Développeur Python", "Habite à Lyon"],
    })
    result = await engine.process_message(
        "je suis dev Python, j'habite à Lyon",
        trust_score=0.5,
        context_messages=[{"author": "Alice", "content": "salut"}],
    )
    assert result is not None
    assert result["user_facts"] == ["Développeur Python", "Habite à Lyon"]
    assert result["trust_delta"] == 0.02

@pytest.mark.asyncio
async def test_process_message_empty_facts(engine):
    engine._openai.complete_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.05, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.01,
        "love_delta": 0.0,
        "user_facts": [],
    })
    result = await engine.process_message(
        "lol c'est marrant",
        trust_score=0.5,
        context_messages=[{"author": "Bob", "content": "hey"}],
    )
    assert result is not None
    assert result["user_facts"] == []

@pytest.mark.asyncio
async def test_fallback_no_user_facts(engine):
    engine._openai = None
    result = await engine.process_message("test message", trust_score=0.5)
    assert result is None

@pytest.mark.asyncio
async def test_user_facts_dicts_are_coerced_to_strings(engine):
    """Régression : DeepSeek renvoie parfois des dicts au lieu de strings.

    Sans coercition, `memory.add(content=<dict>)` plante ensuite sur un `.lower()`
    (« 'dict' object has no attribute 'lower' »). Les dicts doivent être aplatis en
    texte et les entrées vides/non-textuelles jetées.
    """
    engine._openai.complete_structured = AsyncMock(return_value={
        "deltas": {"anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0},
        "new_words": [],
        "trust_delta": 0.0,
        "love_delta": 0.0,
        "user_facts": [{"fact": "Aime le café"}, "Joue à Apex", {}, None, "  "],
    })
    result = await engine.process_message(
        "je bois du café et je joue à Apex",
        trust_score=0.5,
        context_messages=[{"author": "Carl", "content": "yo"}],
    )
    assert result is not None
    assert result["user_facts"] == ["Aime le café", "Joue à Apex"]
