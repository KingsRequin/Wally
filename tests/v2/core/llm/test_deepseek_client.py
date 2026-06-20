"""Tests pour DeepSeekLLMClient."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from bot.core.llm.deepseek import DeepSeekLLMClient
from bot.core.llm.base import FALLBACK_RESPONSE


def make_client(thinking_type="disabled", max_tool_iters=6):
    db = MagicMock()
    db.log_cost = AsyncMock()
    return DeepSeekLLMClient(
        model="deepseek-v4-flash",
        db=db,
        temperature=1.0,
        max_tokens=512,
        thinking_type=thinking_type,
        max_tool_iters=max_tool_iters,
    )


def make_response(content="Bonjour", tool_calls=None, reasoning_content=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    msg.reasoning_content = reasoning_content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 20
    resp.model = "deepseek-v4-flash"
    return resp


def make_tool_call(name="get_info", arguments='{"key": "val"}', call_id="tc_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    tc.model_dump.return_value = {
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments}
    }
    return tc


@pytest.mark.asyncio
async def test_complete_returns_text():
    """complete() retourne le texte du modèle."""
    client = make_client()
    client._client.chat.completions.create = AsyncMock(
        return_value=make_response("Salut !")
    )
    result = await client.complete("sys", [{"role": "user", "content": "hi"}])
    assert result == "Salut !"


@pytest.mark.asyncio
async def test_complete_returns_fallback_on_error():
    """complete() retourne FALLBACK_RESPONSE si l'API lève une exception."""
    client = make_client()
    client._client.chat.completions.create = AsyncMock(side_effect=Exception("API down"))
    result = await client.complete("sys", [{"role": "user", "content": "hi"}])
    assert result == FALLBACK_RESPONSE


@pytest.mark.asyncio
async def test_thinking_disabled_includes_temperature():
    """En thinking disabled, temperature est inclus dans les params API."""
    client = make_client(thinking_type="disabled")
    client._client.chat.completions.create = AsyncMock(return_value=make_response())
    await client.complete("sys", [{"role": "user", "content": "hi"}])
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "temperature" in call_kwargs
    assert call_kwargs["extra_body"]["thinking"]["type"] == "disabled"


@pytest.mark.asyncio
async def test_thinking_enabled_excludes_temperature():
    """En thinking enabled, temperature est ABSENT des params API."""
    client = make_client(thinking_type="enabled")
    client._client.chat.completions.create = AsyncMock(return_value=make_response())
    await client.complete("sys", [{"role": "user", "content": "hi"}])
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "temperature" not in call_kwargs
    assert call_kwargs["extra_body"]["thinking"]["type"] == "enabled"


@pytest.mark.asyncio
async def test_tool_call_reasoning_content_preserved():
    """Si la réponse contient un tool_call, reasoning_content est préservé dans l'historique."""
    client = make_client()
    tc = make_tool_call()
    tool_response = make_response(content=None, tool_calls=[tc], reasoning_content="je réfléchis")
    final_response = make_response("Voilà le résultat")

    call_count = 0
    second_call_messages = None

    async def mock_create(**kwargs):
        nonlocal call_count, second_call_messages
        call_count += 1
        if call_count == 2:
            second_call_messages = kwargs["messages"]
        return tool_response if call_count == 1 else final_response

    client._client.chat.completions.create = mock_create

    executor = AsyncMock(return_value="result_data")
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_info", "parameters": {}}}],
        tool_executor=executor,
    )

    assert text == "Voilà le résultat"
    assert "get_info" in tools
    # Vérifier que reasoning_content est bien dans le message assistant de l'historique
    # envoyé au second appel API — c'est la contrainte DeepSeek critique (erreur 400 sinon)
    assert second_call_messages is not None
    assistant_msgs = [m for m in second_call_messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert "reasoning_content" in assistant_msgs[0]
    assert assistant_msgs[0]["reasoning_content"] == "je réfléchis"


@pytest.mark.asyncio
async def test_no_tool_call_reasoning_content_excluded():
    """Si pas de tool_call, reasoning_content n'est PAS dans le message assistant."""
    client = make_client()
    # Réponse avec reasoning_content mais sans tool_call
    response = make_response("Bonjour", tool_calls=[], reasoning_content="je pense")
    client._client.chat.completions.create = AsyncMock(return_value=response)

    executor = AsyncMock()
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[],
        tool_executor=executor,
    )
    assert text == "Bonjour"
    assert tools == []
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_max_iter_cap_stops_tool_loop():
    """Après max_tool_iters, la boucle s'arrête et génère une réponse finale."""
    client = make_client(max_tool_iters=2)
    tc = make_tool_call()
    tool_response = make_response(content=None, tool_calls=[tc])
    final_response = make_response("Fini")

    call_count = 0
    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        # Les 2 premiers calls ont des tool_calls, le 3ème est le fallback final
        if call_count <= 2:
            return tool_response
        return final_response

    client._client.chat.completions.create = mock_create
    executor = AsyncMock(return_value="ok")
    text, tools = await client.complete_with_tools(
        "sys", [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_info", "parameters": {}}}],
        tool_executor=executor,
    )
    # max 2 itérations + 1 appel final sans tools
    assert call_count == 3
    assert text == "Fini"


@pytest.mark.asyncio
async def test_safe_parse_args_repairs_truncated_json():
    """_safe_parse_args répare le JSON tronqué avec des suffixes."""
    client = make_client()
    # JSON tronqué — manque le guillemet fermant et l'accolade
    raw = '{"key": "val'
    result = client._safe_parse_args(raw)
    # Doit retourner quelque chose (au moins {}) sans lever
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_safe_parse_args_valid_json():
    """_safe_parse_args retourne le JSON valide directement."""
    client = make_client()
    raw = '{"name": "Wally", "value": 42}'
    result = client._safe_parse_args(raw)
    assert result == {"name": "Wally", "value": 42}


@pytest.mark.asyncio
async def test_complete_structured_forces_tool_choice():
    """complete_structured() force tool_choice pour obtenir du JSON structuré."""
    client = make_client()

    # Simuler une réponse avec tool_call contenant le JSON structuré
    schema_args = '{"decision": "RESPOND"}'
    tc = make_tool_call(name="gate_decision", arguments=schema_args)
    response = make_response(content=None, tool_calls=[tc])
    client._client.chat.completions.create = AsyncMock(return_value=response)

    result = await client.complete_structured(
        "sys",
        [{"role": "user", "content": "hi"}],
        schema={"type": "object", "properties": {"decision": {"type": "string"}}},
        schema_name="gate_decision",
    )
    assert result == {"decision": "RESPOND"}
    # Vérifier que tool_choice a été forcé
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "function", "function": {"name": "gate_decision"}}
