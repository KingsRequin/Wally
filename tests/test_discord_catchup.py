"""Tests du rattrapage boot des interactions Discord manquées.

Tout est mocké (aucune connexion Discord) : on vérifie la déduction de la borne
temporelle depuis les logs, le filtrage mention/réponse, et l'ordre chronologique
de rejeu via ``handle_message``.
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from bot.discord.catchup import (
    MAX_LOOKBACK_SECONDS,
    find_last_log_timestamp,
    run_catchup,
)


# ── find_last_log_timestamp ──────────────────────────────────────────────────

def _write_jsonl(path, ts_values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ts in ts_values:
            fh.write(json.dumps({"ts": ts, "type": "message_in"}) + "\n")


def test_last_ts_missing_root(tmp_path):
    assert find_last_log_timestamp(tmp_path / "nope") is None


def test_last_ts_empty(tmp_path):
    (tmp_path / "discord").mkdir()
    assert find_last_log_timestamp(tmp_path) is None


def test_last_ts_returns_global_max_of_latest_date(tmp_path):
    root = tmp_path
    _write_jsonl(root / "discord" / "chanA" / "2026-07-01.jsonl", [10.0, 20.0])
    _write_jsonl(root / "discord" / "chanA" / "2026-07-02.jsonl", [1000.0, 2000.0])
    _write_jsonl(root / "discord" / "chanB" / "2026-07-02.jsonl", [1500.0, 2500.0])
    # Fichier de date ANTÉRIEURE avec un ts artificiellement plus grand : doit être
    # ignoré (seuls les fichiers de la date la plus récente comptent).
    _write_jsonl(root / "discord" / "chanC" / "2026-07-01.jsonl", [99999.0])
    assert find_last_log_timestamp(root) == 2500.0


def test_last_ts_ignores_corrupt_lines(tmp_path):
    root = tmp_path
    d = root / "discord" / "chanA"
    d.mkdir(parents=True)
    # Dernière ligne corrompue → on doit tomber en None pour ce fichier, pas crash.
    (d / "2026-07-02.jsonl").write_text('{"ts": 5.0}\nnot-json\n', encoding="utf-8")
    assert find_last_log_timestamp(root) is None


# ── run_catchup ──────────────────────────────────────────────────────────────

def _async_iter(items):
    async def _gen(*args, **kwargs):
        for it in items:
            yield it
    return _gen


def _make_msg(mid, ts, mentions=None, reference=None, author_bot=False):
    msg = MagicMock(spec=discord.Message)
    msg.id = mid
    msg.author = MagicMock()
    msg.author.bot = author_bot
    msg.mentions = mentions or []
    msg.reference = reference
    msg.created_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    msg.channel = MagicMock()
    return msg


def _make_bot(channels_messages):
    """channels_messages: liste de listes de messages, une par text_channel."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999
    bot.config.discord.per_guild_channel_whitelist = {}
    bot.config.discord.channel_filter_mode = "none"

    channels = []
    for i, msgs in enumerate(channels_messages):
        ch = MagicMock()
        ch.id = 100 + i
        ch.history = MagicMock(side_effect=_async_iter(msgs))
        channels.append(ch)

    guild = MagicMock()
    guild.id = 1
    guild.text_channels = channels
    bot.guilds = [guild]

    conv_log = MagicMock()
    conv_log.root = "logs/conversations"
    bot.conv_log = conv_log
    return bot


@pytest.mark.asyncio
async def test_catchup_no_prior_log_is_noop():
    bot = _make_bot([[]])
    with patch("bot.discord.catchup.find_last_log_timestamp", return_value=None), \
         patch("bot.discord.handlers.handle_message", new=AsyncMock()) as hm:
        await run_catchup(bot)
    hm.assert_not_called()


@pytest.mark.asyncio
async def test_catchup_replays_only_mentions_and_replies_in_order():
    wally = MagicMock()
    wally.id = 999
    other = MagicMock()
    other.id = 42

    # Réponse à un message de Wally (référence résolue).
    ref_to_wally = MagicMock(spec=discord.MessageReference)
    ref_to_wally.message_id = 7
    ref_to_wally.resolved = MagicMock(spec=discord.Message)
    ref_to_wally.resolved.author = wally

    m_ignored = _make_msg(1, ts=100.0, mentions=[other])          # ni mention ni reply
    m_reply = _make_msg(2, ts=300.0, reference=ref_to_wally)      # reply à Wally
    m_mention = _make_msg(3, ts=200.0, mentions=[wally])          # mention @Wally

    bot = _make_bot([[m_ignored, m_reply, m_mention]])
    bot.user = wally

    calls = []

    async def _fake_handle(_bot, message):
        calls.append(message.id)

    with patch("bot.discord.catchup.find_last_log_timestamp", return_value=50.0), \
         patch("bot.discord.handlers.handle_message", new=_fake_handle):
        await run_catchup(bot)

    # Seuls la mention et la réponse sont rejouées, dans l'ordre chronologique (200 puis 300).
    assert calls == [3, 2]


@pytest.mark.asyncio
async def test_catchup_skips_bot_authors():
    wally = MagicMock()
    wally.id = 999
    m_bot = _make_msg(1, ts=100.0, mentions=[wally], author_bot=True)
    bot = _make_bot([[m_bot]])
    bot.user = wally

    with patch("bot.discord.catchup.find_last_log_timestamp", return_value=50.0), \
         patch("bot.discord.handlers.handle_message", new=AsyncMock()) as hm:
        await run_catchup(bot)
    hm.assert_not_called()


@pytest.mark.asyncio
async def test_catchup_lookback_is_capped():
    """Un dernier log très ancien est plafonné à MAX_LOOKBACK_SECONDS."""
    wally = MagicMock()
    wally.id = 999
    bot = _make_bot([[]])
    bot.user = wally
    captured = {}

    ch = bot.guilds[0].text_channels[0]

    def _history(*args, **kwargs):
        captured["after"] = kwargs.get("after")
        async def _gen():
            for _ in ():
                yield _
        return _gen()

    ch.history = MagicMock(side_effect=_history)

    ancient = 1000.0  # ~1970, bien au-delà du plafond
    with patch("bot.discord.catchup.find_last_log_timestamp", return_value=ancient), \
         patch("bot.discord.catchup.time.time", return_value=10_000_000.0), \
         patch("bot.discord.handlers.handle_message", new=AsyncMock()):
        await run_catchup(bot)

    expected_cutoff = 10_000_000.0 - MAX_LOOKBACK_SECONDS
    assert captured["after"].timestamp() == pytest.approx(expected_cutoff)


@pytest.mark.asyncio
async def test_catchup_channel_error_does_not_abort():
    wally = MagicMock()
    wally.id = 999
    good_msg = _make_msg(5, ts=100.0, mentions=[wally])

    bot = _make_bot([[], []])
    bot.user = wally
    # Premier canal lève, second canal fonctionne.
    bot.guilds[0].text_channels[0].history = MagicMock(side_effect=RuntimeError("boom"))
    bot.guilds[0].text_channels[1].history = MagicMock(side_effect=_async_iter([good_msg]))

    calls = []

    async def _fake_handle(_bot, message):
        calls.append(message.id)

    with patch("bot.discord.catchup.find_last_log_timestamp", return_value=50.0), \
         patch("bot.discord.handlers.handle_message", new=_fake_handle):
        await run_catchup(bot)

    assert calls == [5]
