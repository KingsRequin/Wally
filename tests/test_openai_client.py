# tests/test_openai_client.py
"""
Tests for OpenAILLMClient — all OpenAI API calls are mocked.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.llm.openai_client import OpenAILLMClient, estimate_cost, _uses_responses_api
from bot.core.llm.base import FALLBACK_IMAGE_RESPONSE, FALLBACK_RESPONSE


def make_client(model="gpt-5", temperature=0.8, max_tokens=1000,
                reasoning_effort="medium", text_verbosity="medium"):
    db = MagicMock()
    db.log_cost = AsyncMock()
    db.get_cost_since = AsyncMock(return_value=0.042)
    client = OpenAILLMClient(
        model=model, db=db, temperature=temperature, max_tokens=max_tokens,
        reasoning_effort=reasoning_effort, text_verbosity=text_verbosity,
    )
    return client, db


def make_mock_response(content: str, prompt_tokens: int = 50, completion_tokens: int = 30):
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_tokens_details = None
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.usage = usage
    response.choices = [choice]
    return response


def test_estimate_cost_known_model():
    cost = estimate_cost("gpt-5", 1_000_000, 1_000_000)
    assert cost > 0


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost("some-unknown-model-xyz", 1000, 500)
    assert cost > 0


def test_estimate_cost_cached_tokens_reduce_cost():
    full_cost = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=0)
    half_cached = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=1000)
    assert half_cached == pytest.approx(full_cost * 0.5)


def test_estimate_cost_partial_cache():
    full_cost = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=0)
    partial = estimate_cost("gpt-5", 1000, 0, cached_input_tokens=500)
    assert partial == pytest.approx(full_cost * 0.75)


@pytest.mark.asyncio
async def test_complete_success():
    """GPT-5 routes through Responses API."""
    client, db = make_client()

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Bonjour !")) as mock_resp:
        result = await client.complete("System prompt", [{"role": "user", "content": "Hi"}])

    assert result == "Bonjour !"
    mock_resp.assert_called_once()


@pytest.mark.asyncio
async def test_complete_chat_completions_retries_on_rate_limit():
    from openai import RateLimitError
    client, db = make_client(model="gpt-4o")

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
async def test_complete_returns_fallback_on_responses_api_error():
    client, db = make_client()

    with patch.object(
        client._client.responses, "create", new=AsyncMock(side_effect=Exception("API down"))
    ):
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert isinstance(result, str) and len(result) > 0


@pytest.mark.asyncio
async def test_get_daily_cost():
    client, db = make_client()
    cost = await client.get_daily_cost()
    assert cost == 0.042
    db.get_cost_since.assert_called_once()


@pytest.mark.asyncio
async def test_get_monthly_cost():
    client, db = make_client()
    cost = await client.get_monthly_cost()
    assert cost == 0.042


def test_uses_responses_api_detection():
    assert _uses_responses_api("gpt-5-mini") is True
    assert _uses_responses_api("gpt-5.2-mini") is True
    assert _uses_responses_api("gpt-5.4-nano") is True
    assert _uses_responses_api("gpt-5-pro") is True
    assert _uses_responses_api("o1-mini") is True
    assert _uses_responses_api("o3-mini") is True
    assert _uses_responses_api("o4") is True
    assert _uses_responses_api("gpt-4o") is False
    assert _uses_responses_api("gpt-4o-mini") is False


@pytest.mark.asyncio
async def test_responses_api_passes_reasoning_effort():
    client, db = make_client(reasoning_effort="high", text_verbosity="low")

    captured = {}

    async def capture_create(**kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.output_text = "test"
        resp.usage = MagicMock()
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        resp.usage.input_tokens_details = None
        return resp

    with patch.object(client._client.responses, "create", new=AsyncMock(side_effect=capture_create)):
        await client.complete("System", [{"role": "user", "content": "Hi"}])

    assert captured["reasoning"] == {"effort": "high"}
    assert captured["text"]["verbosity"] == "low"
    assert captured["max_output_tokens"] == 1000


@pytest.mark.asyncio
async def test_complete_routes_to_responses_api_for_gpt5():
    client, db = make_client(model="gpt-5-mini")

    with patch.object(client, "_complete_responses_api", new=AsyncMock(return_value="Réponse LLM")) as mock_resp:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_resp.assert_called_once()
    assert result == "Réponse LLM"


@pytest.mark.asyncio
async def test_complete_routes_to_chat_completions_for_gpt4():
    client, db = make_client(model="gpt-4o")

    mock_response = make_mock_response("Chat response")
    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        result = await client.complete("System", [{"role": "user", "content": "Hi"}])

    mock_create.assert_called_once()
    assert result == "Chat response"


# ── Vision ────────────────────────────────────────────────────────────────────


def test_build_image_content_chat_completions():
    client, db = make_client()

    result = client._build_image_content(
        "bonjour", ["http://img1.png", "http://img2.png"], use_responses_api=False
    )

    assert result[0] == {"type": "text", "text": "bonjour"}
    assert result[1] == {"type": "image_url", "image_url": {"url": "http://img1.png"}}
    assert result[2] == {"type": "image_url", "image_url": {"url": "http://img2.png"}}
    assert len(result) == 3


def test_build_image_content_responses_api():
    client, db = make_client()

    result = client._build_image_content(
        "bonjour", ["http://img1.png"], use_responses_api=True
    )

    assert result[0] == {"type": "input_text", "text": "bonjour"}
    assert result[1] == {"type": "input_image", "image_url": "http://img1.png"}
    assert len(result) == 2


@pytest.mark.asyncio
async def test_complete_with_images_transforms_last_message():
    client, db = make_client(model="gpt-4o")

    captured = {}

    async def capture_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return make_mock_response("Je vois une image!")

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=capture_create)
    ):
        await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://cdn.discord.com/img.png"],
        )

    last_content = captured["messages"][-1]["content"]
    assert isinstance(last_content, list)
    assert last_content[0] == {"type": "text", "text": "regarde"}
    assert last_content[1] == {"type": "image_url", "image_url": {"url": "https://cdn.discord.com/img.png"}}


@pytest.mark.asyncio
async def test_complete_image_error_returns_image_fallback():
    client, db = make_client()

    with patch.object(
        client._client.responses,
        "create",
        new=AsyncMock(side_effect=Exception("Invalid image URL")),
    ):
        result = await client.complete(
            "System",
            [{"role": "user", "content": "regarde"}],
            image_urls=["https://invalid.png"],
        )

    assert result == FALLBACK_IMAGE_RESPONSE


@pytest.mark.asyncio
async def test_complete_no_images_uses_generic_fallback():
    client, db = make_client()

    with patch.object(
        client._client.responses,
        "create",
        new=AsyncMock(side_effect=Exception("Server error")),
    ):
        result = await client.complete(
            "System",
            [{"role": "user", "content": "bonjour"}],
        )

    assert result == FALLBACK_RESPONSE
