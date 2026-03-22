import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.fact_extractor import _is_memorable, FactExtractor


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fact_extractor() -> FactExtractor:
    config = MagicMock()
    memory = MagicMock()
    memory.add = AsyncMock()
    memory._alias_cache = {}
    memory.add_alias = MagicMock()
    memory.get_all = AsyncMock(return_value="")
    memory.delete_user_memories = AsyncMock()
    openai = AsyncMock()
    openai.complete_secondary_structured = AsyncMock(
        return_value={"facts": [], "aliases": []}
    )
    db = AsyncMock()
    db.upsert_alias = AsyncMock()
    db.list_aliases = AsyncMock(return_value=[])
    db.insert_session_message = AsyncMock()
    db.delete_session_messages = AsyncMock()
    db.delete_session_messages_before = AsyncMock()
    return FactExtractor(config, memory, openai, db)


# ── Existing tests ─────────────────────────────────────────────────────────────


class TestIsMemorableFilter:
    def test_short_message_rejected(self):
        assert _is_memorable("salut") is False
        assert _is_memorable("yo") is False
        assert _is_memorable("ok bro") is False  # < 15 chars

    def test_emoji_only_rejected(self):
        assert _is_memorable("😂😂😂") is False
        assert _is_memorable("🔥🔥") is False

    def test_single_interjection_rejected(self):
        assert _is_memorable("lol") is False
        assert _is_memorable("mdrrr") is False
        assert _is_memorable("ptdrrr") is False
        assert _is_memorable("xdddd") is False
        assert _is_memorable("hahaha") is False
        assert _is_memorable("okkk") is False
        assert _is_memorable("ggg") is False
        assert _is_memorable("ouiii") is False
        assert _is_memorable("nooon") is False
        assert _is_memorable("^^") is False
        assert _is_memorable("+1") is False
        assert _is_memorable("rip") is False
        assert _is_memorable("aaah") is False
        assert _is_memorable("ooooh") is False

    def test_all_interjections_rejected(self):
        assert _is_memorable("non non non non") is False
        assert _is_memorable("lol mdr ptdr xd") is False

    def test_interjection_with_content_passes(self):
        assert _is_memorable("mdr c'est trop vrai ce que tu dis") is True
        assert _is_memorable("oui je suis développeur Python") is True
        assert _is_memorable("lol j'habite à Marseille") is True

    def test_informative_message_passes(self):
        assert _is_memorable("je suis développeur Python depuis 3 ans") is True
        assert _is_memorable("j'habite à Lyon, je bosse dans une startup") is True
        assert _is_memorable("franchement j'adore le metal scandinave") is True

    def test_medium_message_passes(self):
        assert _is_memorable("c'est vraiment intéressant comme approche") is True

    def test_whitespace_handling(self):
        assert _is_memorable("  lol  ") is False
        assert _is_memorable("  mdr  ") is False
        assert _is_memorable("  je suis dev Python  ") is True  # > 15 chars after strip? Actually "je suis dev Python" is 18 chars


# ── Buffer tests ───────────────────────────────────────────────────────────────


class TestFactExtractorBuffer:
    @pytest.mark.asyncio
    async def test_non_memorable_not_buffered(self):
        fe = _make_fact_extractor()
        fe.record_message("ch1", "discord", "u1", "User1", "lol", is_reply=False)
        assert len(fe._buffers.get("ch1", {}).get("messages", [])) == 0

    @pytest.mark.asyncio
    async def test_memorable_message_buffered(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch1",
            "discord",
            "u1",
            "User1",
            "je suis développeur Python depuis 5 ans",
            is_reply=False,
        )
        assert len(fe._buffers["ch1"]["messages"]) == 1

    @pytest.mark.asyncio
    async def test_reply_activates_chain(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch1",
            "discord",
            "u1",
            "User1",
            "oui je suis d'accord avec toi sur ce point",
            is_reply=True,
        )
        assert fe._buffers["ch1"]["reply_chain_active"] is True

    @pytest.mark.asyncio
    async def test_non_memorable_still_updates_last_activity(self):
        fe = _make_fact_extractor()
        before = time.time()
        fe.record_message("ch2", "discord", "u2", "User2", "lol", is_reply=False)
        assert fe._buffers["ch2"]["last_activity"] >= before

    @pytest.mark.asyncio
    async def test_platform_stored_in_buffer(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch3", "twitch", "u3", "User3",
            "je joue à Minecraft depuis 10 ans",
            is_reply=False,
        )
        assert fe._buffers["ch3"]["platform"] == "twitch"

    @pytest.mark.asyncio
    async def test_db_insert_called_for_memorable(self):
        fe = _make_fact_extractor()
        fe.record_message(
            "ch4", "discord", "u4", "User4",
            "je suis étudiant en informatique à Paris",
            is_reply=False,
        )
        # Allow fire-and-forget tasks to run
        await asyncio.sleep(0)
        fe._db.insert_session_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_not_called_for_non_memorable(self):
        fe = _make_fact_extractor()
        fe.record_message("ch5", "discord", "u5", "User5", "ok", is_reply=False)
        await asyncio.sleep(0)
        fe._db.insert_session_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_triggered_at_threshold(self):
        fe = _make_fact_extractor()
        memorable = "je travaille comme ingénieur dans l'aéronautique"
        for i in range(5):
            fe.record_message(
                "ch6", "discord", f"u{i}", f"User{i}", memorable, is_reply=False
            )
        # Give tasks a chance to run
        await asyncio.sleep(0)
        # complete_secondary_structured should have been called (flush triggered)
        fe._openai.complete_secondary_structured.assert_called()

    @pytest.mark.asyncio
    async def test_reply_chain_prevents_flush_at_threshold(self):
        fe = _make_fact_extractor()
        memorable = "j'adore programmer en Rust depuis deux ans maintenant"
        # Activate reply chain first
        fe.record_message("ch7", "discord", "u0", "User0", memorable, is_reply=True)
        # Add more messages up to threshold (but not safety cap)
        for i in range(1, 5):
            fe.record_message(
                "ch7", "discord", f"u{i}", f"User{i}", memorable, is_reply=False
            )
        await asyncio.sleep(0)
        # No flush yet because reply_chain_active is True
        fe._openai.complete_secondary_structured.assert_not_called()


# ── analyze_channel_messages tests ────────────────────────────────────────────


class TestFactExtractorAnalyzeChannel:
    @pytest.mark.asyncio
    async def test_analyze_channel_messages(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(
            return_value={
                "facts": [
                    {
                        "target": "Alice",
                        "target_user_id": "discord:111",
                        "facts": ["Dev Python"],
                    }
                ],
                "aliases": [],
            }
        )
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "je suis dev Python"
        msg1.created_at.timestamp.return_value = time.time()

        msg2 = MagicMock()
        msg2.author.bot = False
        msg2.author.id = 222
        msg2.author.display_name = "Bob"
        msg2.content = "moi je préfère Rust"
        msg2.created_at.timestamp.return_value = time.time()

        result = await fe.analyze_channel_messages(
            [msg1, msg2], "discord", "ch1", bot_user_id=999
        )
        assert result >= 0
        fe._openai.complete_secondary_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_too_few_messages(self):
        fe = _make_fact_extractor()
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "hello"
        msg1.created_at.timestamp.return_value = time.time()

        with pytest.raises(ValueError):
            await fe.analyze_channel_messages(
                [msg1], "discord", "ch1", bot_user_id=999
            )

    @pytest.mark.asyncio
    async def test_bot_messages_filtered(self):
        fe = _make_fact_extractor()
        bot_msg = MagicMock()
        bot_msg.author.bot = True
        bot_msg.author.id = 999
        bot_msg.author.display_name = "Wally"
        bot_msg.content = "je suis un bot qui répond aux messages"
        bot_msg.created_at.timestamp.return_value = time.time()

        human_msg = MagicMock()
        human_msg.author.bot = False
        human_msg.author.id = 111
        human_msg.author.display_name = "Alice"
        human_msg.content = "bonjour tout le monde!"
        human_msg.created_at.timestamp.return_value = time.time()

        # Only 1 human message after filtering → ValueError
        with pytest.raises(ValueError):
            await fe.analyze_channel_messages(
                [bot_msg, human_msg], "discord", "ch1", bot_user_id=999
            )

    @pytest.mark.asyncio
    async def test_memory_add_called_for_known_user(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(
            return_value={
                "facts": [
                    {
                        "target": "Alice",
                        "target_user_id": "discord:111",
                        "facts": ["Aime le Python", "Habite à Paris"],
                    }
                ],
                "aliases": [],
            }
        )
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "j'adore Python et j'habite à Paris"
        msg1.created_at.timestamp.return_value = time.time()

        msg2 = MagicMock()
        msg2.author.bot = False
        msg2.author.id = 222
        msg2.author.display_name = "Bob"
        msg2.content = "cool, moi je suis à Lyon"
        msg2.created_at.timestamp.return_value = time.time()

        await fe.analyze_channel_messages(
            [msg1, msg2], "discord", "ch1", bot_user_id=999
        )
        fe._memory.add.assert_called_once()
        call_args = fe._memory.add.call_args
        assert call_args[0][0] == "discord"
        assert call_args[0][1] == "111"

    @pytest.mark.asyncio
    async def test_alias_with_high_confidence_stored(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(
            return_value={
                "facts": [],
                "aliases": [
                    {
                        "nickname": "alice_twitch",
                        "resolved_to": "Alice",
                        "resolved_user_id": "discord:111",
                        "confidence": 0.9,
                    }
                ],
            }
        )
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "je joue aussi sur Twitch sous alice_twitch"
        msg1.created_at.timestamp.return_value = time.time()

        msg2 = MagicMock()
        msg2.author.bot = False
        msg2.author.id = 222
        msg2.author.display_name = "Bob"
        msg2.content = "ah sympa je te follow sur Twitch"
        msg2.created_at.timestamp.return_value = time.time()

        await fe.analyze_channel_messages(
            [msg1, msg2], "discord", "ch1", bot_user_id=999
        )

        await asyncio.sleep(0)  # let background tasks run
        fe._db.upsert_alias.assert_called_once()
        fe._memory.add_alias.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_facts_with_categories(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(return_value={
            "facts": [
                {
                    "target": "Alice",
                    "target_user_id": "discord:111",
                    "scope": "personal",
                    "facts": [
                        {"text": "Works as a developer", "category": "FAIT"},
                        {"text": "Lives in Lyon", "category": "FAIT"},
                    ],
                }
            ],
            "aliases": [],
        })
        fe._db.list_aliases = AsyncMock(return_value=[])
        fe._db.list_memory_users = AsyncMock(return_value=[])

        messages = [
            {"user_id": "111", "display_name": "Alice", "content": "I'm a developer living in Lyon"},
        ]
        count = await fe._extract_facts(messages, "discord", "chan1")
        assert count == 1

        # Verify category was passed to memory.add()
        call_args = fe._memory.add.call_args
        assert call_args.kwargs.get("category") == "FAIT"

    @pytest.mark.asyncio
    async def test_extract_facts_mixed_categories(self):
        """When facts have mixed categories, dominant one wins."""
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(return_value={
            "facts": [
                {
                    "target": "Bob",
                    "target_user_id": "discord:222",
                    "scope": "personal",
                    "facts": [
                        {"text": "Prefers dark mode", "category": "PREF"},
                        {"text": "Likes Python", "category": "PREF"},
                        {"text": "Works at Google", "category": "FAIT"},
                    ],
                }
            ],
            "aliases": [],
        })
        fe._db.list_aliases = AsyncMock(return_value=[])
        fe._db.list_memory_users = AsyncMock(return_value=[])

        messages = [
            {"user_id": "222", "display_name": "Bob", "content": "I prefer dark mode and Python, I work at Google"},
        ]
        count = await fe._extract_facts(messages, "discord", "chan1")
        assert count == 1

        call_args = fe._memory.add.call_args
        assert call_args.kwargs.get("category") == "PREF"

    @pytest.mark.asyncio
    async def test_extract_facts_backward_compat_strings(self):
        """Old string format should still work with default FAIT category."""
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(return_value={
            "facts": [
                {
                    "target": "Carol",
                    "target_user_id": "discord:333",
                    "scope": "personal",
                    "facts": ["Lives in Paris", "Speaks French"],
                }
            ],
            "aliases": [],
        })
        fe._db.list_aliases = AsyncMock(return_value=[])
        fe._db.list_memory_users = AsyncMock(return_value=[])

        messages = [
            {"user_id": "333", "display_name": "Carol", "content": "I live in Paris and speak French"},
        ]
        count = await fe._extract_facts(messages, "discord", "chan1")
        assert count == 1

        call_args = fe._memory.add.call_args
        assert call_args.kwargs.get("category") == "FAIT"

    @pytest.mark.asyncio
    async def test_alias_with_low_confidence_ignored(self):
        fe = _make_fact_extractor()
        fe._openai.complete_secondary_structured = AsyncMock(
            return_value={
                "facts": [],
                "aliases": [
                    {
                        "nickname": "maybe_alice",
                        "resolved_to": "Alice",
                        "resolved_user_id": "discord:111",
                        "confidence": 0.5,
                    }
                ],
            }
        )
        msg1 = MagicMock()
        msg1.author.bot = False
        msg1.author.id = 111
        msg1.author.display_name = "Alice"
        msg1.content = "je suis peut-être sur Twitch aussi"
        msg1.created_at.timestamp.return_value = time.time()

        msg2 = MagicMock()
        msg2.author.bot = False
        msg2.author.id = 222
        msg2.author.display_name = "Bob"
        msg2.content = "peut-être oui, qui sait vraiment"
        msg2.created_at.timestamp.return_value = time.time()

        await fe.analyze_channel_messages(
            [msg1, msg2], "discord", "ch1", bot_user_id=999
        )

        await asyncio.sleep(0)
        fe._db.upsert_alias.assert_not_called()
