import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from bot.intelligence.thought_progress import ThoughtProgressJudge, VERDICTS

PROMPTS = Path("bot/persona/prompts")


def _judge(reply: str):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=reply)
    return ThoughtProgressJudge(llm, PROMPTS), llm


@pytest.mark.asyncio
async def test_verdicts_set():
    assert VERDICTS == frozenset({"PROGRESSE", "RESSASSE", "DIVAGUE"})


@pytest.mark.asyncio
@pytest.mark.parametrize("reply,expected", [
    ("RESSASSE", "RESSASSE"),
    ("PROGRESSE", "PROGRESSE"),
    ("DIVAGUE", "DIVAGUE"),
    ("Verdict : RESSASSE, c'est la 4e fois.", "RESSASSE"),
    ("  progresse  ", "PROGRESSE"),
])
async def test_judge_parses_verdict(reply, expected):
    judge, _ = _judge(reply)
    out = await judge.judge("une pensée", "un focus", ["pensée A", "pensée B"])
    assert out == expected


@pytest.mark.asyncio
async def test_judge_defaults_to_progresse_on_garbage():
    judge, _ = _judge("je ne sais pas trop")
    out = await judge.judge("une pensée", None, [])
    assert out == "PROGRESSE"


@pytest.mark.asyncio
async def test_judge_passes_focus_and_thoughts_to_llm():
    judge, llm = _judge("RESSASSE")
    await judge.judge("PENSEE_X", "FOCUS_Y", ["ANCIENNE_Z"])
    # Le contenu utilisateur transmis au LLM contient bien les 3 éléments.
    user_msg = llm.complete.call_args.args[1][0]["content"]
    assert "PENSEE_X" in user_msg
    assert "FOCUS_Y" in user_msg
    assert "ANCIENNE_Z" in user_msg
