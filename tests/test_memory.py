# tests/test_memory.py
"""
Tests for MemoryService — mem0/Qdrant is mocked entirely.
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from bot.core.memory import MemoryService


def make_config(window_size=5, token_threshold=100):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = 15
    return config


def test_append_and_get_context():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "Hello")
    svc.append_message("ch1", "Bob", "World")
    ctx = svc.get_context("ch1")
    assert len(ctx) == 2
    assert ctx[0]["author"] == "Alice"
    assert ctx[0]["content"] == "Hello"
    assert ctx[1]["author"] == "Bob"
    assert "timestamp" in ctx[0]


def test_context_window_trims_to_max():
    svc = MemoryService(make_config(window_size=3))
    for i in range(5):
        svc.append_message("ch1", "User", f"Message {i}")
    ctx = svc.get_context("ch1")
    assert len(ctx) == 3
    assert ctx[0]["content"] == "Message 2"  # oldest kept


def test_empty_context_returns_empty_list():
    svc = MemoryService(make_config())
    assert svc.get_context("nonexistent") == []


def test_channels_are_independent():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "In channel 1")
    svc.append_message("ch2", "Bob", "In channel 2")
    assert len(svc.get_context("ch1")) == 1
    assert len(svc.get_context("ch2")) == 1
    assert svc.get_context("ch1")[0]["author"] == "Alice"


def test_user_id_namespacing():
    svc = MemoryService(make_config())
    assert svc._user_id("discord", "123") == "discord:123"
    assert svc._user_id("twitch", "alice") == "twitch:alice"


@pytest.mark.asyncio
async def test_get_context_summarized_returns_messages_when_below_threshold():
    svc = MemoryService(make_config(token_threshold=10000))
    svc.append_message("ch1", "Alice", "Short message")
    result = await svc.get_context_summarized_if_needed("ch1")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


@pytest.mark.asyncio
async def test_get_context_summarized_when_no_openai_returns_as_is():
    # Without openai client set, should return messages unmodified even if over threshold
    svc = MemoryService(make_config(token_threshold=1))
    svc.append_message("ch1", "Alice", "A" * 10)
    result = await svc.get_context_summarized_if_needed("ch1")
    assert len(result) == 1  # no openai, no summarization


@pytest.mark.asyncio
async def test_add_graceful_when_mem0_unavailable():
    svc = MemoryService(make_config())
    # mem0 is not initialized (no Qdrant in test env) — should not raise
    await svc.add("discord", "user1", "Alice likes cats")


@pytest.mark.asyncio
async def test_search_returns_empty_when_mem0_unavailable():
    svc = MemoryService(make_config())
    result = await svc.search("discord", "user1", "cats")
    assert result == ""


@pytest.mark.asyncio
async def test_search_filters_low_score_results():
    """Les résultats avec un score inférieur au seuil sont exclus."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()
    svc._mem0.search = MagicMock(return_value={
        "results": [
            {"memory": "Fan de jeux vidéo", "score": 0.85},
            {"memory": "A mentionné la pluie", "score": 0.15},  # sous le seuil
            {"memory": "Développeur Python", "score": 0.60},
        ]
    })
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        result = await svc.search("discord", "user1", "passions")
    assert "Fan de jeux vidéo" in result
    assert "Développeur Python" in result
    assert "A mentionné la pluie" not in result


@pytest.mark.asyncio
async def test_search_returns_empty_when_all_scores_too_low():
    """Si tous les résultats sont sous le seuil, retourner chaîne vide."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()
    svc._mem0.search = MagicMock(return_value={
        "results": [
            {"memory": "Fait non pertinent", "score": 0.10},
        ]
    })
    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        result = await svc.search("discord", "user1", "quelque chose")
    assert result == ""


@pytest.mark.asyncio
async def test_add_logs_stored_memories():
    """add() journalise ce que mem0 stocke effectivement via le retour de mem0.add()."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()
    svc._mem0.add = MagicMock(return_value={
        "results": [
            {"id": "abc", "memory": "Fan de Rust", "event": "ADD"},
            {"id": "def", "memory": "ancien fait", "event": "DELETE"},
        ]
    })

    logged = []
    with patch("bot.core.memory.logger") as mock_logger:
        mock_logger.debug = MagicMock(side_effect=lambda msg, **kw: logged.append(kw))
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
            await svc.add("discord", "user1", "Fan de Rust")

    # L'événement ADD doit être journalisé, pas le DELETE
    assert any(kw.get("event") == "ADD" and "Rust" in kw.get("mem", "") for kw in logged)


@pytest.mark.asyncio
async def test_consolidation_adds_before_deleting():
    """La consolidation ajoute la synthèse AVANT de supprimer les anciens souvenirs."""
    from bot.core.memory import _CONSOLIDATION_THRESHOLD
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()

    # Simuler un dépassement du seuil
    old_memories = [{"id": f"id{i}", "memory": f"fait {i}"} for i in range(_CONSOLIDATION_THRESHOLD + 5)]
    svc._mem0.get_all = MagicMock(return_value={"results": old_memories})
    svc._mem0.add = MagicMock(return_value={"results": []})
    svc._mem0.delete = MagicMock(return_value=None)

    call_order = []
    svc._mem0.add.side_effect = lambda *a, **kw: call_order.append("add") or {"results": []}
    svc._mem0.delete.side_effect = lambda *a, **kw: call_order.append("delete")

    mock_openai = MagicMock()
    mock_openai.complete_secondary = AsyncMock(return_value="- fait synthétisé")
    svc.set_openai_client(mock_openai)

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await svc._maybe_consolidate("discord", "user1")

    # Le premier appel doit être "add" (synthèse), puis les "delete" (anciens)
    assert call_order[0] == "add", "La synthèse doit être ajoutée avant toute suppression"
    assert all(op == "delete" for op in call_order[1:]), "Les appels suivants doivent tous être des suppressions"
    assert len(call_order) == 1 + len(old_memories)  # 1 add + N deletes


def test_get_all_contexts_returns_all_sorted():
    svc = MemoryService(make_config())
    svc.append_message("ch1", "Alice", "First")
    svc.append_message("ch2", "Bob", "Second")
    # Force timestamps to ensure deterministic order
    svc._context_windows["ch1"][0]["timestamp"] = 1.0
    svc._context_windows["ch2"][0]["timestamp"] = 2.0
    all_ctx = svc.get_all_contexts()
    assert len(all_ctx) == 2
    assert all_ctx[0]["author"] == "Alice"
    assert all_ctx[1]["author"] == "Bob"


def test_get_all_contexts_empty():
    svc = MemoryService(make_config())
    assert svc.get_all_contexts() == []


@pytest.mark.asyncio
async def test_summarize_messages_multi_pass():
    """When messages span >1 chunk, a final combining call is made."""
    svc = MemoryService(make_config())

    call_count = 0

    async def fake_complete(system, messages, purpose="summary"):
        nonlocal call_count
        call_count += 1
        return f"summary_{call_count}"

    mock_openai = MagicMock()
    mock_openai.complete_secondary = fake_complete
    svc.set_openai_client(mock_openai)

    # 15 messages → 2 chunks (10 + 5) → 2 chunk summaries + 1 final = 3 calls
    messages = [
        {"author": "U", "content": f"msg{i}", "timestamp": float(i)}
        for i in range(15)
    ]
    result = await svc._summarize_messages(messages)

    assert call_count == 3
    assert result == "summary_3"  # the final combining call


# ── Prelude buffer ────────────────────────────────────────────────────────────

def make_config_prelude(window_size=5, token_threshold=100, prelude_size=3):
    config = MagicMock()
    config.bot.context_window_size = window_size
    config.bot.context_token_threshold = token_threshold
    config.bot.prelude_window_size = prelude_size
    return config


def test_append_prelude_circular():
    svc = MemoryService(make_config_prelude(prelude_size=3))
    for i in range(5):
        svc.append_prelude("ch1", "User", f"msg {i}")
    result = svc.get_prelude("ch1")
    assert len(result) == 3
    assert result[0]["content"] == "msg 2"  # oldest kept


def test_get_prelude_returns_copy():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    copy = svc.get_prelude("ch1")
    copy.append({"author": "X", "content": "injected", "timestamp": 0})
    assert len(svc.get_prelude("ch1")) == 1  # original untouched


def test_prelude_independent_from_context_windows():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "prelude msg")
    svc.append_message("ch1", "Alice", "context msg")
    assert len(svc.get_prelude("ch1")) == 1
    assert len(svc.get_context("ch1")) == 1
    assert svc.get_prelude("ch1")[0]["content"] == "prelude msg"
    assert svc.get_context("ch1")[0]["content"] == "context msg"


def test_prelude_reset_clears_buffer():
    svc = MemoryService(make_config_prelude())
    svc.append_prelude("ch1", "Alice", "hello")
    assert len(svc.get_prelude("ch1")) == 1
    # reset_all() doit aussi purger _prelude_windows
    import asyncio
    asyncio.run(svc.reset_all())
    assert svc.get_prelude("ch1") == []


@pytest.mark.asyncio
async def test_memory_add_passes_username_to_db():
    """Vérifie que memory.add() transmet le username à db.upsert_memory_user."""
    from bot.core.memory import MemoryService

    config = make_config()
    svc = MemoryService(config)

    mock_mem0 = MagicMock()
    mock_mem0.add.return_value = {"results": []}
    svc._mem0_init_attempted = True  # must be set BEFORE assigning _mem0
    svc._mem0 = mock_mem0

    mock_db = MagicMock()
    mock_db.upsert_memory_user = AsyncMock()
    svc.set_db(mock_db)

    await svc.add("discord", "123", "some content", username="OlafMC")

    mock_db.upsert_memory_user.assert_called_once()
    call_args = mock_db.upsert_memory_user.call_args
    # Verify "OlafMC" is passed as username
    assert "OlafMC" in call_args.args or call_args.kwargs.get("username") == "OlafMC"


@pytest.mark.asyncio
async def test_add_with_category_passes_metadata():
    """Category should be included in mem0 metadata alongside origin."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()
    svc._mem0.add = MagicMock(return_value={"results": []})
    mock_db = MagicMock()
    mock_db.upsert_memory_user = AsyncMock()
    svc.set_db(mock_db)

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs))):
        await svc.add("discord", "123", "Likes Python", category="FAIT")

    call_args = svc._mem0.add.call_args
    metadata = call_args.kwargs.get("metadata", {})
    assert metadata["category"] == "FAIT"
    assert metadata["origin"] == "discord:123"


@pytest.mark.asyncio
async def test_search_top_match_returns_best():
    """search_top_match returns the highest-scoring memory with its score."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"memory": "aime le Python", "score": 0.6},
            {"memory": "joue à Apex", "score": 0.85},
            {"memory": "habite à Lyon", "score": 0.4},
        ]
    }
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "quel jeu tu fais")
    assert result is not None
    text, score = result
    assert text == "joue à Apex"
    assert score == 0.85


@pytest.mark.asyncio
async def test_search_top_match_no_results():
    """search_top_match returns None when no results above threshold."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {"results": []}
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "random query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_below_min_score():
    """search_top_match returns None when all results are below _MIN_SEARCH_SCORE."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"memory": "some fact", "score": 0.1},
            {"memory": "another fact", "score": 0.2},
        ]
    }
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_qdrant_error():
    """search_top_match returns None and logs warning on Qdrant failure."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    mock_mem0 = MagicMock()
    mock_mem0.search.side_effect = Exception("Qdrant unavailable")
    svc._mem0 = mock_mem0
    result = await svc.search_top_match("discord", "12345", "query")
    assert result is None


@pytest.mark.asyncio
async def test_search_top_match_empty_query():
    """search_top_match returns None for empty/whitespace queries."""
    svc = MemoryService(make_config())
    svc._init_mem0()
    svc._mem0 = MagicMock()
    result = await svc.search_top_match("discord", "12345", "")
    assert result is None
    result2 = await svc.search_top_match("discord", "12345", "   ")
    assert result2 is None
