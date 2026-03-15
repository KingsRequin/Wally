# tests/test_openai_client.py
"""
Tests for OpenAIClient — all OpenAI API calls are mocked.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.openai_client import OpenAIClient, estimate_cost, _uses_responses_api


def make_config():
    config = MagicMock()
    config.openai.primary_model = "gpt-4o"
    config.openai.secondary_model = "gpt-4o-mini"
    config.openai.temperature = 0.8
    config.openai.max_tokens = 1000
    return config


def make_db():
    db = MagicMock()
    db.log_cost = AsyncMock()
    db.get_cost_since = AsyncMock(return_value=0.042)
    return db


def make_mock_response(content: str, prompt_tokens: int = 50, completion_tokens: int = 30):
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.usage = usage
    response.choices = [choice]
    return response


def test_estimate_cost_known_model():
    cost = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
    assert cost > 0


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost("some-unknown-model-xyz", 1000, 500)
    assert cost > 0


@pytest.mark.asyncio
async def test_complete_success():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("Bonjour !")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.complete("System prompt", [{"role": "user", "content": "Hi"}])

    assert result == "Bonjour !"
    db.log_cost.assert_called_once()


@pytest.mark.asyncio
async def test_complete_uses_primary_model_by_default():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("OK")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        await client.complete("System", [{"role": "user", "content": "Hello"}])

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_complete_secondary_uses_secondary_model():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("Summary")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        await client.complete_secondary("System", [{"role": "user", "content": "Summarise"}])

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_complete_retries_on_rate_limit_then_succeeds():
    from openai import RateLimitError
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("OK after retry")
    side_effects = [
        RateLimitError("rate limit", response=MagicMock(status_code=429), body=None),
        mock_response,
    ]
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=side_effects)
    ):
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert result == "OK after retry"


@pytest.mark.asyncio
async def test_complete_returns_fallback_after_all_retries_fail():
    from openai import RateLimitError
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    error = RateLimitError("rate limit", response=MagicMock(status_code=429), body=None)
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=error)
    ):
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert isinstance(result, str) and len(result) > 0  # fallback message


@pytest.mark.asyncio
async def test_get_daily_cost():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)
    cost = await client.get_daily_cost()
    assert cost == 0.042
    db.get_cost_since.assert_called_once()


@pytest.mark.asyncio
async def test_get_monthly_cost():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)
    cost = await client.get_monthly_cost()
    assert cost == 0.042


def test_uses_responses_api_detection():
    assert _uses_responses_api("gpt-5-mini") is True
    assert _uses_responses_api("gpt-5.2-mini") is True
    assert _uses_responses_api("o1-mini") is True
    assert _uses_responses_api("o3-mini") is True
    assert _uses_responses_api("o4") is True
    assert _uses_responses_api("gpt-4o") is False
    assert _uses_responses_api("gpt-4o-mini") is False


@pytest.mark.asyncio
async def test_complete_routes_to_responses_api_for_gpt5():
    config = make_config()
    config.openai.primary_model = "gpt-5-mini"
    db = make_db()
    client = OpenAIClient(config, db)

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Réponse LLM")) as mock_resp:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_resp.assert_called_once()
    assert result == "Réponse LLM"


@pytest.mark.asyncio
async def test_complete_routes_to_chat_completions_for_gpt4():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_mock_response("Chat response")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_create.assert_called_once()
    assert result == "Chat response"
