"""Tests for ClaudeLLMClient.complete_stream()."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from bot.core.llm.claude_client import ClaudeLLMClient
from bot.core.llm.base import FALLBACK_RESPONSE


def make_client():
    db = MagicMock()
    db.log_cost = AsyncMock()
    return ClaudeLLMClient(
        model="claude-sonnet-4-6",
        db=db,
        temperature=0.8,
        max_tokens=1000,
    )


@pytest.mark.asyncio
async def test_complete_stream_yields_chunks():
    """complete_stream() yields text deltas from Anthropic streaming API."""
    client = make_client()

    async def mock_text_stream():
        for text in ["Salut", " toi", " !"]:
            yield text

    @asynccontextmanager
    async def mock_stream_ctx(*args, **kwargs):
        mock_stream = MagicMock()
        mock_stream.text_stream = mock_text_stream()
        yield mock_stream

    with patch.object(client._client.messages, "stream", mock_stream_ctx):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == ["Salut", " toi", " !"]


@pytest.mark.asyncio
async def test_complete_stream_error_yields_fallback():
    """On error, complete_stream() yields FALLBACK_RESPONSE."""
    client = make_client()

    @asynccontextmanager
    async def boom(*args, **kwargs):
        raise Exception("API error")
        yield  # make it a generator

    with patch.object(client._client.messages, "stream", boom):
        chunks = []
        async for chunk in client.complete_stream("sys", [{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

    assert chunks == [FALLBACK_RESPONSE]
