import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.discord.voice.brain import generate_search_filler


def _bot():
    bot = MagicMock()
    bot.emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0
    }
    bot.emotion.get_secondary_emotions.return_value = []
    bot.prompts.build_voice_system = MagicMock(return_value="SYSTEM")
    bot.persona.build_prompt_block.return_value = "PERSONA"
    bot.persona.emotion_directives = {}
    bot.persona.weekday_directives = {}
    bot.persona.composite_directives = {}
    bot.persona.secondary_directives = {}
    return bot


@pytest.mark.asyncio
async def test_filler_renvoie_amorce_et_bruits():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(
        return_value={"amorce": "attends je regarde", "bruits": ["mh...", "ok je vois"]}
    )
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"] == "attends je regarde"
    assert out["bruits"] == ["mh...", "ok je vois"]


@pytest.mark.asyncio
async def test_filler_repli_si_llm_echoue():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(side_effect=RuntimeError("boom"))
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"]                      # repli non vide
    assert isinstance(out["bruits"], list)


@pytest.mark.asyncio
async def test_filler_repli_si_amorce_vide():
    bot = _bot()
    bot.llm_secondary.complete_structured = AsyncMock(return_value={"amorce": "", "bruits": []})
    out = await generate_search_filler(bot, "prix ps5")
    assert out["amorce"]                      # repli car amorce vide
