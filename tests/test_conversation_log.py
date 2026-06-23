import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.core.conversation_log import (
    ConversationLogger,
    _safe_segment,
    new_trace_id,
)


def _today_file(root, platform, channel):
    day = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")
    return root / platform / channel / f"{day}.jsonl"


@pytest.mark.asyncio
async def test_log_writes_jsonl_to_expected_path(tmp_path):
    log = ConversationLogger(root=tmp_path)
    log.start()
    log.log("discord", "general", "message_in", trace_id="42", author="Bob", content="salut")
    await log.stop()

    path = _today_file(tmp_path, "discord", "general")
    assert path.exists()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    rec = records[0]
    assert rec["type"] == "message_in"
    assert rec["trace_id"] == "42"
    assert rec["author"] == "Bob"
    assert rec["content"] == "salut"
    assert isinstance(rec["ts"], float)


@pytest.mark.asyncio
async def test_events_grouped_by_platform_and_channel(tmp_path):
    log = ConversationLogger(root=tmp_path)
    log.start()
    log.log("discord", "general", "message_in", trace_id="1")
    log.log("discord", "general", "message_out", trace_id="1")
    log.log("twitch", "kamet0", "message_in", trace_id="2")
    await log.stop()

    discord_path = _today_file(tmp_path, "discord", "general")
    twitch_path = _today_file(tmp_path, "twitch", "kamet0")
    assert len(discord_path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(twitch_path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.asyncio
async def test_long_fields_are_truncated(tmp_path):
    log = ConversationLogger(root=tmp_path)
    log.start()
    log.log("discord", "general", "llm_call", trace_id="3", prompt="x" * 20000)
    await log.stop()

    rec = json.loads(_today_file(tmp_path, "discord", "general").read_text(encoding="utf-8"))
    assert rec["prompt"].endswith("car.]")
    assert len(rec["prompt"]) < 20000


@pytest.mark.asyncio
async def test_appends_across_multiple_flushes(tmp_path):
    log = ConversationLogger(root=tmp_path)
    log.start()
    log.log("discord", "general", "message_in", trace_id="1")
    log.log("discord", "general", "message_in", trace_id="2")
    await log.stop()

    path = _today_file(tmp_path, "discord", "general")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_safe_segment_sanitizes_path_separators():
    assert _safe_segment("a/b\\c") == "a_b_c"
    assert _safe_segment("") == "unknown"
    assert _safe_segment("#général!") == "général"


def test_new_trace_id_is_unique():
    assert new_trace_id("spontaneous") != new_trace_id("spontaneous")
    assert new_trace_id("x").startswith("x:")
