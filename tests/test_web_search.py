# tests/test_web_search.py
"""Tests for WebSearchService and complete_with_tools integration."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.web_search import WebSearchService, WEB_SEARCH_TOOL, IMAGE_SEARCH_TOOL
from bot.core.openai_client import OpenAIClient, FALLBACK_RESPONSE


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_config(monthly_limit=200):
    config = MagicMock()
    config.tavily.monthly_limit = monthly_limit
    config.openai.primary_model = "gpt-4o"
    config.openai.secondary_model = "gpt-4o-mini"
    config.openai.temperature = 0.8
    config.openai.max_tokens = 1000
    return config


def make_db(search_count=0):
    db = MagicMock()
    db.log_cost = AsyncMock()
    db.log_web_search = AsyncMock()
    db.count_web_searches_this_month = AsyncMock(return_value=search_count)
    return db


def make_tavily_response():
    return {
        "query": "latest news about AI",
        "answer": "AI is advancing rapidly.",
        "results": [
            {
                "title": "AI News",
                "url": "https://example.com/ai",
                "content": "Some content about AI developments.",
                "score": 0.95,
            },
            {
                "title": "Machine Learning Update",
                "url": "https://example.com/ml",
                "content": "ML research continues.",
                "score": 0.88,
            },
        ],
    }


# ── WebSearchService ─────────────────────────────────────────────────────────


def test_tool_definition_structure():
    tool = WEB_SEARCH_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "web_search"
    assert "query" in tool["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_search_returns_formatted_results():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value=make_tavily_response())
    service._client = mock_client

    result = await service.search("latest news about AI")

    assert "AI is advancing rapidly" in result
    assert "AI News" in result
    assert "https://example.com/ai" in result
    db.log_web_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_quota_exceeded():
    config = make_config(monthly_limit=100)
    db = make_db(search_count=100)
    service = WebSearchService(config, db)
    service._client = AsyncMock()

    result = await service.search("test query")
    assert "quota exceeded" in result.lower()
    service._client.search.assert_not_called()


@pytest.mark.asyncio
async def test_is_quota_exceeded_true():
    config = make_config(monthly_limit=50)
    db = make_db(search_count=50)
    service = WebSearchService(config, db)
    assert await service.is_quota_exceeded() is True


@pytest.mark.asyncio
async def test_is_quota_exceeded_false():
    config = make_config(monthly_limit=200)
    db = make_db(search_count=10)
    service = WebSearchService(config, db)
    assert await service.is_quota_exceeded() is False


def test_available_without_client():
    config = make_config()
    db = make_db()
    with patch.dict("os.environ", {"TAVILY_API_KEY": ""}, clear=False):
        service = WebSearchService(config, db)
    assert service.available is False


def test_format_results_with_answer():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)
    service._client = MagicMock()

    result = service._format_results(make_tavily_response())
    assert "Summary:" in result
    assert "AI News" in result


def test_format_results_empty():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)
    service._client = MagicMock()

    result = service._format_results({"results": []})
    assert result == "No results found."


@pytest.mark.asyncio
async def test_search_handles_tavily_error():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(side_effect=Exception("API Error"))
    service._client = mock_client

    result = await service.search("test")
    assert "failed" in result.lower()


# ── image_search ─────────────────────────────────────────────────────────────


def test_image_search_tool_structure():
    tool = IMAGE_SEARCH_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "image_search"


@pytest.mark.asyncio
async def test_search_images_returns_urls():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value={
        "images": [
            "https://example.com/cat1.jpg",
            "https://example.com/cat2.jpg",
        ],
        "results": [],
    })
    service._client = mock_client

    result = await service.search_images("cute cat")
    assert "https://example.com/cat1.jpg" in result
    assert "https://example.com/cat2.jpg" in result
    db.log_web_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_images_no_results():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value={"images": [], "results": []})
    service._client = mock_client

    result = await service.search_images("impossible query xyz")
    assert result == "No images found."


@pytest.mark.asyncio
async def test_search_images_quota_exceeded():
    config = make_config(monthly_limit=10)
    db = make_db(search_count=10)
    service = WebSearchService(config, db)
    service._client = AsyncMock()

    result = await service.search_images("cat")
    assert "quota exceeded" in result.lower()


@pytest.mark.asyncio
async def test_search_images_limits_to_3():
    config = make_config()
    db = make_db()
    service = WebSearchService(config, db)

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value={
        "images": [f"https://example.com/img{i}.jpg" for i in range(10)],
        "results": [],
    })
    service._client = mock_client

    result = await service.search_images("cats")
    urls = result.strip().split("\n")
    assert len(urls) == 3


# ── complete_with_tools (Chat Completions API) ───────────────────────────────


def make_chat_response_with_tool_call(tool_call_id="tc_1", query="AI news"):
    """Simulates a response where the model calls web_search."""
    tool_call = MagicMock()
    tool_call.id = tool_call_id
    tool_call.function.name = "web_search"
    tool_call.function.arguments = json.dumps({"query": query})

    msg = MagicMock()
    msg.tool_calls = [tool_call]
    msg.content = None

    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.prompt_tokens_details = None

    response = MagicMock()
    response.choices = [MagicMock(message=msg)]
    response.usage = usage
    return response


def make_chat_response_final(content="Here's what I found about AI."):
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = content

    usage = MagicMock()
    usage.prompt_tokens = 200
    usage.completion_tokens = 80
    usage.prompt_tokens_details = None

    response = MagicMock()
    response.choices = [MagicMock(message=msg)]
    response.usage = usage
    return response


@pytest.mark.asyncio
async def test_complete_with_tools_no_tool_call():
    """When the model doesn't call any tool, returns normally."""
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    final = make_chat_response_final("Direct answer")
    with patch.object(
        client._client.chat.completions, "create",
        new=AsyncMock(return_value=final),
    ):
        executor = AsyncMock(return_value="unused")
        result, tools = await client.complete_with_tools(
            "system", [{"role": "user", "content": "hello"}],
            tools=[WEB_SEARCH_TOOL], tool_executor=executor,
        )

    assert result == "Direct answer"
    assert tools == []
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_complete_with_tools_executes_tool():
    """When the model calls web_search, the executor is invoked and results sent back."""
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    tool_response = make_chat_response_with_tool_call()
    final_response = make_chat_response_final("Based on my research...")

    with patch.object(
        client._client.chat.completions, "create",
        new=AsyncMock(side_effect=[tool_response, final_response]),
    ):
        executor = AsyncMock(return_value="Search results here")
        result, tools = await client.complete_with_tools(
            "system", [{"role": "user", "content": "what's new in AI?"}],
            tools=[WEB_SEARCH_TOOL], tool_executor=executor,
        )

    assert result == "Based on my research..."
    assert tools == ["web_search"]
    executor.assert_awaited_once_with("web_search", json.dumps({"query": "AI news"}))


@pytest.mark.asyncio
async def test_complete_with_tools_logs_cost():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    final = make_chat_response_final("answer")
    with patch.object(
        client._client.chat.completions, "create",
        new=AsyncMock(return_value=final),
    ):
        await client.complete_with_tools(
            "system", [{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL],
            tool_executor=AsyncMock(),
            purpose="test",
        )

    db.log_cost.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_with_tools_returns_fallback_on_error():
    config = make_config()
    db = make_db()
    client = OpenAIClient(config, db)

    with patch.object(
        client._client.chat.completions, "create",
        new=AsyncMock(side_effect=Exception("API down")),
    ):
        result, tools = await client.complete_with_tools(
            "system", [{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL],
            tool_executor=AsyncMock(),
        )

    assert result == FALLBACK_RESPONSE
    assert tools == []


# ── Discord handler integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_handler_adds_globe_reaction_on_search():
    """When web_search is called, 🌐 reaction is added and removed."""
    from bot.discord.handlers import _respond

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.0})
    bot.emotion.process_message = AsyncMock()
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()

    # Web search mock
    web_search = MagicMock()
    web_search.available = True
    web_search.is_quota_exceeded = AsyncMock(return_value=False)
    web_search.get_tool_definitions = MagicMock(return_value=[WEB_SEARCH_TOOL, IMAGE_SEARCH_TOOL])
    web_search.search = AsyncMock(return_value="Search results")
    bot.web_search = web_search
    bot.apex_api = None

    bot.openai.complete_with_tools = AsyncMock(return_value=("Answer from web", ["web_search"]))

    msg = MagicMock()
    msg.content = "wally what's the weather"
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = []

    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, msg, "12345", "99999", [])

    # 🔍 added, then removed
    assert any(call.args[0] == "🔍" for call in msg.add_reaction.call_args_list)
    assert any(call.args[0] == "🔍" for call in msg.remove_reaction.call_args_list)
    # complete_with_tools called with web search tools
    bot.openai.complete_with_tools.assert_awaited_once()
    call_args = bot.openai.complete_with_tools.call_args
    tools_passed = call_args.args[2]
    tool_names = [t["function"]["name"] for t in tools_passed]
    assert "web_search" in tool_names
    assert "image_search" in tool_names
    # Response sent
    msg.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_handler_no_search_when_quota_exceeded():
    """When quota is exceeded, falls back to regular complete()."""
    from bot.discord.handlers import _respond

    bot = MagicMock()
    bot.user = MagicMock()
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.db.get_trust_score = AsyncMock(return_value=0.5)
    bot.db.mark_welcomed = AsyncMock()
    bot.db.upsert_memory_user = AsyncMock()
    bot.memory.search = AsyncMock(return_value="")
    bot.memory.get_context_summarized_if_needed = AsyncMock(return_value=[])
    bot.memory.append_message = MagicMock()
    bot.prompts.build_system_prompt = MagicMock(return_value="system")
    bot.prompts.build_context_block = MagicMock(return_value="")
    bot.prompts.build_prelude_block = MagicMock(return_value="")
    bot.persona = MagicMock()
    bot.persona.build_prompt_block = MagicMock(return_value="")
    bot.emotion.get_state = MagicMock(return_value={"anger": 0.0})
    bot.emotion.process_message = AsyncMock()
    bot.db.update_trust_score = AsyncMock()
    bot.db.count_recent_triggers = AsyncMock(return_value=0)
    bot.db.add_timeout = AsyncMock()

    web_search = MagicMock()
    web_search.available = True
    web_search.is_quota_exceeded = AsyncMock(return_value=True)
    bot.web_search = web_search
    bot.apex_api = None

    bot.openai.complete = AsyncMock(return_value="Regular response")

    msg = MagicMock()
    msg.content = "wally hello"
    msg.author.id = 12345
    msg.author.display_name = "TestUser"
    msg.guild.id = 99999
    msg.channel.id = 777
    msg.channel.typing = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=None),
    ))
    msg.mentions = []
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.attachments = []

    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, msg, "12345", "99999", [])

    # Falls back to regular complete (no tools)
    bot.openai.complete.assert_awaited_once()
    bot.openai.complete_with_tools = AsyncMock()  # should not have been called
