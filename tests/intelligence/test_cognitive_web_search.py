import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence.cognitive_loop import CognitiveLoop
from bot.intelligence.meta_agent import MetaDecision
from bot.intelligence.reasoning_agent import ReasoningResult


def _result(*, with_search, query="quelle météo demain"):
    decisions = [MetaDecision(action="THINK")]
    if with_search:
        decisions.append(MetaDecision(action="ACT", act_name="web_search",
                                      act_args={"query": query}))
    return ReasoningResult(thought_text="je me demande...", thought_fact_id=1,
                           decisions=decisions)


def _loop(reasoning, web_search, **kw):
    return CognitiveLoop(
        MagicMock(), reasoning, MagicMock(),
        web_search=web_search, **kw,
    )


def _web(available=True, quota=False, result="→ il fera beau"):
    w = MagicMock()
    w.available = available
    w.is_quota_exceeded = AsyncMock(return_value=quota)
    w.search = AsyncMock(return_value=result)
    return w


@pytest.mark.asyncio
async def test_no_tag_no_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=False))
    web.search.assert_not_called()
    reasoning.reason.assert_not_called()
    assert out.thought_text == "je me demande..."


@pytest.mark.asyncio
async def test_tag_triggers_search_and_second_pass():
    second = ReasoningResult(thought_text="ah donc il fera beau", thought_fact_id=2,
                             decisions=[MetaDecision(action="THINK")])
    reasoning = MagicMock()
    reasoning.reason = AsyncMock(return_value=second)
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True, query="météo demain"))
    web.search.assert_awaited_once()
    assert web.search.await_args.args[0] == "météo demain"
    assert ctx.web_finding is not None and "il fera beau" in ctx.web_finding
    reasoning.reason.assert_awaited_once()
    assert out is second


def test_fresh_loop_cooldown_ts_is_never_sentinel():
    """Non-régression bug#2 (reboot hôte) : `_web_search_cooldown_ts` doit valoir
    -inf à l'instantiation, pas 0.0. `time.monotonic()` compte depuis le boot
    machine ; un sentinel `0.0` ferait lire `now - 0.0 = uptime`, donc « recherché
    à l'instant » pendant les 45 premières minutes suivant chaque reboot hôte."""
    reasoning = MagicMock()
    web = _web()
    loop = _loop(reasoning, web)
    assert loop._web_search_cooldown_ts == float("-inf")


@pytest.mark.asyncio
async def test_fresh_loop_search_not_blocked_by_cooldown_regardless_of_uptime():
    """Sur une boucle fraîche (aucune recherche jamais faite), une recherche web
    n'est pas bloquée par le cooldown — vrai quel que soit l'uptime réel de la
    machine, sans monkeypatch de time.monotonic (c'est justement le bug#2)."""
    reasoning = MagicMock()
    reasoning.reason = AsyncMock(return_value=_result(with_search=False))
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True, query="test"))
    web.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_cooldown_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    loop._web_search_cooldown_ts = time.monotonic()  # vient de chercher
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_quota_exceeded_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web(quota=True)
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_blocks_search():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web(available=False)
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_web_search_none_is_noop():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    loop = _loop(reasoning, None)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True))
    reasoning.reason.assert_not_called()
    assert out.thought_fact_id == 1


@pytest.mark.asyncio
async def test_empty_query_is_noop():
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    await loop._maybe_web_search(ctx, _result(with_search=True, query=""))
    web.search.assert_not_called()


@pytest.mark.asyncio
async def test_search_exception_keeps_first_pass():
    """web.search raises → 1st-pass result returned, no exception propagated."""
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    web.search = AsyncMock(side_effect=Exception("timeout"))
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True))
    reasoning.reason.assert_not_called()
    assert out.thought_fact_id == 1


@pytest.mark.asyncio
async def test_quota_check_exception_keeps_first_pass():
    """is_quota_exceeded raises → search never called, 1st-pass result returned."""
    reasoning = MagicMock()
    reasoning.reason = AsyncMock()
    web = _web()
    web.is_quota_exceeded = AsyncMock(side_effect=Exception("boom"))
    loop = _loop(reasoning, web)
    ctx = SimpleNamespace(web_finding=None)
    out = await loop._maybe_web_search(ctx, _result(with_search=True))
    web.search.assert_not_called()
    assert out.thought_fact_id == 1
