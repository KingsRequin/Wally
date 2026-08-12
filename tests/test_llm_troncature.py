# tests/test_llm_troncature.py
"""Une réponse coupée par le plafond de tokens ne doit pas passer en silence.

Vécu le 2026-08-12 : le pass de dé-polissage du journal tournait sur le client
secondaire, plafonné à 1000 tokens de sortie. Le brouillon d'un jour chargé ne
rentrait pas ; la sortie est repartie coupée en pleine phrase, a été publiée sur
Discord et archivée. Aucun log ne signalait la coupure — `complete()` rend un
`str`, et `finish_reason` n'était lu nulle part dans le client DeepSeek.
"""
from types import SimpleNamespace

import pytest
from loguru import logger

from bot.core.llm.deepseek import DeepSeekLLMClient


def _response(content: str, finish_reason: str = "stop"):
    msg = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=1000),
        model="deepseek-v4-flash",
    )


class _FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeDB:
    async def log_cost(self, **_kwargs) -> None:
        return None


def _client(response) -> DeepSeekLLMClient:
    client = DeepSeekLLMClient(model="deepseek-v4-flash", db=_FakeDB())
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(response)))
    return client


@pytest.fixture
def journal_logs():
    lignes: list[str] = []
    sink = logger.add(lambda m: lignes.append(m), level="WARNING")
    yield lignes
    logger.remove(sink)


@pytest.mark.asyncio
async def test_troncature_signalee(journal_logs):
    client = _client(_response("mon ego en a profité, je vais pas", finish_reason="length"))

    texte = await client.complete("sys", [{"role": "user", "content": "salut"}], purpose="journal_voice_pass")

    assert texte == "mon ego en a profité, je vais pas"  # rendu quand même : au décideur de trancher
    trace = " ".join(journal_logs)
    assert "journal_voice_pass" in trace
    assert "coup" in trace.lower() or "tronqu" in trace.lower()


@pytest.mark.asyncio
async def test_reponse_complete_ne_logge_rien(journal_logs):
    client = _client(_response("Une phrase finie."))

    await client.complete("sys", [{"role": "user", "content": "salut"}])

    assert journal_logs == []


@pytest.mark.asyncio
async def test_max_tokens_transmis_a_l_api():
    """Le plafond passé par l'appelant doit primer sur celui du rôle."""
    client = _client(_response("ok."))
    fake = client._client.chat.completions

    await client.complete("sys", [{"role": "user", "content": "salut"}], max_tokens=4000)

    assert fake.calls[-1]["max_tokens"] == 4000
