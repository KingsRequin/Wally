# tests/test_structured_outputs.py
"""
Tests for OpenAIClient.complete_secondary_structured() — JSON schema structured outputs.
All OpenAI API calls are mocked.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.openai_client import OpenAIClient


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "number"},
    },
    "required": ["name", "score"],
    "additionalProperties": False,
}

SAMPLE_RESULT = {"name": "wally", "score": 0.9}


def make_config(secondary_model: str = "gpt-4o"):
    config = MagicMock()
    config.openai.primary_model = "gpt-5"
    config.openai.secondary_model = secondary_model
    config.openai.temperature = 0.8
    config.openai.max_tokens = 1000
    config.openai.reasoning_effort = "none"
    config.openai.text_verbosity = None
    return config


def make_db():
    db = MagicMock()
    db.log_cost = AsyncMock()
    return db


def make_chat_response(content: str, finish_reason: str = "stop"):
    """Build a mock Chat Completions response."""
    usage = MagicMock()
    usage.prompt_tokens = 50
    usage.completion_tokens = 20
    usage.prompt_tokens_details = None

    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason

    response = MagicMock()
    response.usage = usage
    response.choices = [choice]
    return response


def make_responses_api_response(text: str, status: str = "completed"):
    """Build a mock Responses API response."""
    usage = MagicMock()
    usage.input_tokens = 50
    usage.output_tokens = 20
    usage.input_tokens_details = None

    response = MagicMock()
    response.output_text = text
    response.status = status
    response.usage = usage
    return response


@pytest.mark.asyncio
async def test_structured_chat_completions():
    """Chat Completions path returns parsed dict and passes response_format with json_schema."""
    config = make_config(secondary_model="gpt-4o")  # Chat Completions model
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_chat_response(json.dumps(SAMPLE_RESULT), finish_reason="stop")
    captured = {}

    async def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_response

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=capture_create)
    ):
        result = await client.complete_secondary_structured(
            system_prompt="Extract info.",
            messages=[{"role": "user", "content": "Wally scored 0.9"}],
            schema=SAMPLE_SCHEMA,
            schema_name="response",
        )

    # Verify return type and content
    assert isinstance(result, dict)
    assert result == SAMPLE_RESULT

    # Verify response_format was passed with json_schema
    assert "response_format" in captured
    rf = captured["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "response"
    assert rf["json_schema"]["schema"] == SAMPLE_SCHEMA
    assert rf["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_structured_truncated_response_raises():
    """Truncated response (finish_reason=length) raises RuntimeError."""
    config = make_config(secondary_model="gpt-4o")  # Chat Completions model
    db = make_db()
    client = OpenAIClient(config, db)

    # Response is truncated — finish_reason = "length"
    mock_response = make_chat_response(
        json.dumps({"name": "partial"}), finish_reason="length"
    )

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ):
        with pytest.raises(RuntimeError, match="truncated"):
            await client.complete_secondary_structured(
                system_prompt="Extract info.",
                messages=[{"role": "user", "content": "Test"}],
                schema=SAMPLE_SCHEMA,
            )


@pytest.mark.asyncio
async def test_structured_responses_api():
    """Responses API path (o1/o3/o4/gpt-5 models) returns parsed dict and passes text.format with json_schema."""
    config = make_config(secondary_model="o3-mini")  # Responses API model
    db = make_db()
    client = OpenAIClient(config, db)

    mock_response = make_responses_api_response(
        json.dumps(SAMPLE_RESULT), status="completed"
    )
    captured = {}

    async def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_response

    with patch.object(
        client._client.responses, "create", new=AsyncMock(side_effect=capture_create)
    ):
        result = await client.complete_secondary_structured(
            system_prompt="Extract info.",
            messages=[{"role": "user", "content": "Wally scored 0.9"}],
            schema=SAMPLE_SCHEMA,
            schema_name="my_schema",
        )

    # Verify return type and content
    assert isinstance(result, dict)
    assert result == SAMPLE_RESULT

    # Verify text.format was passed with json_schema
    assert "text" in captured
    text_format = captured["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "my_schema"
    assert text_format["schema"] == SAMPLE_SCHEMA
