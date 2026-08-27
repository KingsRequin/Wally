"""La part du prompt servie par le cache est ÉCRITE, pas seulement calculée.

Les deux providers l'exposent et les deux la calculaient déjà pour facturer au
bon tarif — puis la jetaient. `cost_log` ne portait donc que `input_tokens`, et
aucune question du genre « que coûterait de faire varier le préfixe du prompt ? »
n'avait de réponse chiffrée. C'est exactement la signature que ce dépôt combat :
la donnée existe, personne ne la garde, et l'absence ne se voit pas.

Ces tests portent sur le COMPORTEMENT (ce qui arrive en base), jamais sur une
ligne d'implémentation : asserter le source figerait le défaut le jour où le
chemin change.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "t.db"))
    yield base
    await base.close()


async def test_log_cost_persiste_la_part_cachee(db):
    await db.log_cost("gpt-5.6-luna", 1000, 50, 0.01, purpose="twitch_response",
                      cached_input_tokens=800)
    row = await db.fetch_one("SELECT input_tokens, cached_input_tokens FROM cost_log")
    assert row["input_tokens"] == 1000
    # Comprise DANS l'entrée, jamais en plus : 800 des 1000 étaient au chaud.
    assert row["cached_input_tokens"] == 800


async def test_log_cost_sans_cache_vaut_zero_et_pas_null(db):
    """Azure TTS et les vieux modèles n'exposent rien. `0` doit rester sommable."""
    await db.log_cost("azure-tts", 0, 0, 0.0, purpose="voice_tts")
    row = await db.fetch_one("SELECT cached_input_tokens FROM cost_log")
    assert row["cached_input_tokens"] == 0


async def test_openai_transmet_la_part_cachee():
    """Le client tient `cached` pour estimer le coût — il doit aussi l'écrire."""
    from bot.core.llm.openai_client import OpenAILLMClient

    client = OpenAILLMClient.__new__(OpenAILLMClient)
    client._model = "gpt-test"
    client._db = MagicMock()
    client._db.log_cost = AsyncMock()

    await client._log_cost(input_tokens=1000, output_tokens=20, cost=0.01,
                           purpose="test", user_id=None, cached_input_tokens=768)
    assert client._db.log_cost.await_args.kwargs["cached_input_tokens"] == 768


async def test_deepseek_transmet_prompt_cache_hit_tokens():
    from bot.core.llm.deepseek import DeepSeekLLMClient

    client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
    client._model = "deepseek-chat"
    client._db = MagicMock()
    client._db.log_cost = AsyncMock()

    usage = MagicMock(prompt_tokens=1000, completion_tokens=20,
                      prompt_cache_hit_tokens=896, prompt_cache_miss_tokens=104)
    await client._log_cost(MagicMock(usage=usage, model="deepseek-chat"), "test", None)
    assert client._db.log_cost.await_args.kwargs["cached_input_tokens"] == 896


async def test_deepseek_sans_champ_de_cache_ne_leve_pas():
    """Vieux modèle ou mock : `_deepseek_cost` retombe déjà sur 0, pas nous."""
    from bot.core.llm.deepseek import DeepSeekLLMClient

    client = DeepSeekLLMClient.__new__(DeepSeekLLMClient)
    client._model = "deepseek-chat"
    client._db = MagicMock()
    client._db.log_cost = AsyncMock()

    usage = MagicMock(spec=["prompt_tokens", "completion_tokens"])
    usage.prompt_tokens, usage.completion_tokens = 500, 10
    await client._log_cost(MagicMock(usage=usage, model="deepseek-chat"), "test", None)
    assert client._db.log_cost.await_args.kwargs["cached_input_tokens"] == 0
