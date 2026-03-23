# tests/test_structured_outputs.py
"""
Tests for OpenAILLMClient.complete_structured() — JSON schema structured outputs.
All OpenAI API calls are mocked.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.llm.openai_client import OpenAILLMClient


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


def make_client(model: str = "gpt-4o"):
    db = MagicMock()
    db.log_cost = AsyncMock()
    return OpenAILLMClient(
        model=model, db=db, temperature=0.8, max_tokens=1000,
        reasoning_effort="none", text_verbosity="medium",
    ), db


def make_chat_response(content: str, finish_reason: str = "stop"):
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
    client, db = make_client(model="gpt-4o")

    mock_response = make_chat_response(json.dumps(SAMPLE_RESULT), finish_reason="stop")
    captured = {}

    async def capture_create(**kwargs):
        captured.update(kwargs)
        return mock_response

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(side_effect=capture_create)
    ):
        result = await client.complete_structured(
            system_prompt="Extract info.",
            messages=[{"role": "user", "content": "Wally scored 0.9"}],
            schema=SAMPLE_SCHEMA,
            schema_name="response",
        )

    assert isinstance(result, dict)
    assert result == SAMPLE_RESULT
    assert "response_format" in captured
    rf = captured["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "response"
    assert rf["json_schema"]["schema"] == SAMPLE_SCHEMA
    assert rf["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_structured_truncated_response_raises():
    client, db = make_client(model="gpt-4o")

    mock_response = make_chat_response(
        json.dumps({"name": "partial"}), finish_reason="length"
    )

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ):
        with pytest.raises(RuntimeError, match="truncated"):
            await client.complete_structured(
                system_prompt="Extract info.",
                messages=[{"role": "user", "content": "Test"}],
                schema=SAMPLE_SCHEMA,
            )


@pytest.mark.asyncio
async def test_structured_responses_api():
    client, db = make_client(model="o3-mini")

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
        result = await client.complete_structured(
            system_prompt="Extract info.",
            messages=[{"role": "user", "content": "Wally scored 0.9"}],
            schema=SAMPLE_SCHEMA,
            schema_name="my_schema",
        )

    assert isinstance(result, dict)
    assert result == SAMPLE_RESULT
    assert "text" in captured
    text_format = captured["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "my_schema"
    assert text_format["schema"] == SAMPLE_SCHEMA
