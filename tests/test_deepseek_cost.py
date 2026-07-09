# tests/test_deepseek_cost.py
"""Tests du calcul de coût DeepSeek (table de prix + lecture de l'usage).

Prix de référence : https://api-docs.deepseek.com/quick_start/pricing/
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

import bot.core.llm.deepseek as ds
from bot.core.llm.deepseek import _deepseek_cost, _is_deepseek_peak


def _usage(prompt_tokens, completion_tokens, hit=None, miss=None):
    u = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    if hit is not None:
        u.prompt_cache_hit_tokens = hit
    if miss is not None:
        u.prompt_cache_miss_tokens = miss
    return u


def test_pro_avec_cache_hit_et_miss():
    # pro : 0.003625 / 0.435 / 0.87 par 1M
    cost = _deepseek_cost("deepseek-v4-pro", _usage(10_000, 2_000, hit=1_000, miss=9_000))
    expected = (1_000 * 0.003625 + 9_000 * 0.435 + 2_000 * 0.87) / 1_000_000
    assert cost == pytest.approx(expected)


def test_fallback_tout_en_cache_miss_si_champs_absents():
    cost = _deepseek_cost("deepseek-v4-pro", _usage(10_000, 2_000))
    expected = (10_000 * 0.435 + 2_000 * 0.87) / 1_000_000
    assert cost == pytest.approx(expected)


def test_flash_et_alias_chat_reasoner():
    expected = (1_000 * 0.14 + 500 * 0.28) / 1_000_000
    for model in ("deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"):
        assert _deepseek_cost(model, _usage(1_000, 500)) == pytest.approx(expected)


def test_prefixe_le_plus_long():
    # un id daté doit retomber sur le tarif pro, pas flash
    cost = _deepseek_cost("deepseek-v4-pro-2026-06", _usage(1_000, 0, hit=0, miss=1_000))
    assert cost == pytest.approx(1_000 * 0.435 / 1_000_000)


def test_modele_inconnu_utilise_fallback_flash():
    assert _deepseek_cost("modele-inconnu", _usage(1_000, 500)) == pytest.approx(
        (1_000 * 0.14 + 500 * 0.28) / 1_000_000
    )


def test_peak_inactif_par_defaut():
    # _DEEPSEEK_PEAK_START vaut None → jamais de pointe, même en pleine plage UTC.
    assert ds._DEEPSEEK_PEAK_START is None
    in_peak = datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc)  # 02:00 UTC
    assert _is_deepseek_peak(in_peak) is False


def test_peak_plages_utc_une_fois_active(monkeypatch):
    monkeypatch.setattr(ds, "_DEEPSEEK_PEAK_START", date(2026, 7, 15))
    peak = lambda h: _is_deepseek_peak(datetime(2026, 8, 1, h, 0, tzinfo=timezone.utc))
    # Pointe : 01:00–04:00 et 06:00–10:00
    assert peak(1) and peak(3) and peak(6) and peak(9)
    # Creux : 00:00, 04:00–06:00, 10:00+
    assert not peak(0) and not peak(4) and not peak(5) and not peak(10) and not peak(23)


def test_peak_avant_date_activation(monkeypatch):
    monkeypatch.setattr(ds, "_DEEPSEEK_PEAK_START", date(2026, 7, 15))
    # 02:00 UTC mais la veille de l'activation → tarif normal.
    assert _is_deepseek_peak(datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc)) is False


def test_cout_double_en_heure_de_pointe(monkeypatch):
    monkeypatch.setattr(ds, "_DEEPSEEK_PEAK_START", date(2026, 7, 15))
    usage = _usage(10_000, 2_000, hit=1_000, miss=9_000)
    normal = (1_000 * 0.003625 + 9_000 * 0.435 + 2_000 * 0.87) / 1_000_000
    peak_ts = datetime(2026, 8, 1, 7, 0, tzinfo=timezone.utc)   # 07:00 UTC = pointe
    valley_ts = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)  # 12:00 UTC = creux
    assert _deepseek_cost("deepseek-v4-pro", usage, now=peak_ts) == pytest.approx(normal * 2)
    assert _deepseek_cost("deepseek-v4-pro", usage, now=valley_ts) == pytest.approx(normal)


class _FakeStream:
    """Imite le context manager `chat.completions.stream()` du SDK openai."""

    def __init__(self):
        self._chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
            for t in ("Hel", "lo")
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()

    async def get_final_completion(self):
        usage = SimpleNamespace(
            prompt_tokens=1_000, completion_tokens=500,
            prompt_cache_hit_tokens=200, prompt_cache_miss_tokens=800,
        )
        return SimpleNamespace(model="deepseek-v4-pro", usage=usage)


@pytest.mark.asyncio
async def test_complete_stream_loggue_le_cout():
    from unittest.mock import AsyncMock, MagicMock

    from bot.core.llm.deepseek import DeepSeekLLMClient

    db = MagicMock()
    db.log_cost = AsyncMock()
    client = DeepSeekLLMClient("deepseek-v4-pro", db)
    client._client = MagicMock()
    client._client.chat.completions.stream = MagicMock(return_value=_FakeStream())

    out = ""
    async for piece in client.complete_stream(
        "sys", [{"role": "user", "content": "hi"}], purpose="resp", user_id="42"
    ):
        out += piece

    assert out == "Hello"
    db.log_cost.assert_awaited_once()
    kwargs = db.log_cost.await_args.kwargs
    expected = (200 * 0.003625 + 800 * 0.435 + 500 * 0.87) / 1_000_000
    assert kwargs["cost_usd"] == pytest.approx(expected)
    # include_usage doit être demandé, sinon DeepSeek n'émet pas l'usage final
    assert client._client.chat.completions.stream.call_args.kwargs["stream_options"] == {
        "include_usage": True
    }
