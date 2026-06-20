import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.embeddings import make_embedding_fn


class _Resp:
    def __init__(self, vec):
        self.data = [MagicMock(embedding=vec)]


@pytest.mark.asyncio
async def test_embedding_caches_and_logs_cost():
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=_Resp([0.1, 0.2, 0.3]))
    db = MagicMock()
    db.log_cost = AsyncMock()

    embed = await make_embedding_fn(client, db)
    v1 = await embed("hello")
    v2 = await embed("hello")  # cache hit

    assert v1 == [0.1, 0.2, 0.3]
    assert v2 == v1
    client.embeddings.create.assert_awaited_once()       # cache: une seule vraie requête
    db.log_cost.assert_awaited()                          # coût loggé
    assert db.log_cost.await_args.kwargs.get("purpose") == "embedding"
