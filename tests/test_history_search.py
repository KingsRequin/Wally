"""Tests de la recherche plein texte dans l'historique Discord.

Aucune connexion Discord : on écrit de vrais fichiers JSONL dans `tmp_path` avec
la même arborescence que `ConversationLogger`
(`{root}/discord/{canal}/{YYYY-MM-DD}.jsonl`) et on vérifie le matching, les
filtres, l'exclusion des MP et la robustesse aux données abîmées.
"""
import json
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from bot.core.history_search import (
    DEFAULT_LIMIT,
    HISTORY_SEARCH_TOOL,
    MAX_LIMIT,
    VOICE_HISTORY_SEARCH_TOOL,
    HistorySearchService,
    extract_terms,
    search_logs,
)
from bot.discord.handlers import _respond
from tests.test_discord_handlers import make_bot, make_message

_PARIS = ZoneInfo("Europe/Paris")


def _ts(day: str, hour: int = 12) -> float:
    """Epoch d'un jour donné à `hour` heure de Paris (le jour du fichier)."""
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hour, tzinfo=_PARIS).timestamp()


def _write(root, channel: str, day: str, records: list[dict]) -> None:
    path = root / "discord" / channel / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            rec.setdefault("type", "message_in")
            rec.setdefault("ts", _ts(day))
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.fixture
def logs(tmp_path):
    """Un petit historique : 3 salons, 3 jours, un MP, un message de Wally."""
    _write(tmp_path, "Purgatoire_general", "2026-03-10", [
        {"author": "Azraël (@azrael)", "author_id": "111",
         "content": "j'ai eu mon bachelier avec mention"},
        {"author": "Bob (@bob)", "author_id": "222", "content": "bravo mec"},
    ])
    _write(tmp_path, "Purgatoire_general", "2026-07-01", [
        {"author": "Bob (@bob)", "author_id": "222",
         "content": "les bacheliers de cette année sont perdus"},
        {"type": "message_out", "author": "Wally",
         "content": "un bachelier qui sait pas lire, quelle époque"},
        {"type": "gate_decision", "decision": "ignore", "content": "bachelier"},
    ])
    _write(tmp_path, "Purgatoire_shitpost", "2026-07-02", [
        {"author": "Azraël (@azrael)", "author_id": "111",
         "content": "le débarquement du bachelier"},
    ])
    _write(tmp_path, "dm", "2026-07-02", [
        {"author": "Secret (@secret)", "author_id": "999",
         "content": "mon bachelier est un secret"},
    ])
    return tmp_path


# ── extract_terms ────────────────────────────────────────────────────────────

def test_terms_normalized_and_filtered():
    assert extract_terms("Bachelier À l'École") == ["bachelier", "ecole"]


def test_terms_empty_when_only_noise():
    assert extract_terms("  ?! a ") == []


# ── Matching plein texte ─────────────────────────────────────────────────────

def test_finds_all_occurrences_across_channels_and_days(logs):
    hits, total = search_logs(logs, ["bachelier"])
    # 3 messages entrants + celui de Wally ; le MP et l'event non conversationnel
    # sont exclus.
    assert total == 4
    contents = [h.content for h in hits]
    assert "j'ai eu mon bachelier avec mention" in contents
    assert "un bachelier qui sait pas lire, quelle époque" in contents


def test_prefix_match_catches_plural(logs):
    hits, _ = search_logs(logs, ["bachelier"], channel="general", after=date(2026, 7, 1))
    assert any("bacheliers" in h.content for h in hits)


def test_match_is_accent_and_case_insensitive(tmp_path):
    _write(tmp_path, "salon", "2026-07-01",
           [{"author": "A", "content": "Une SOIRÉE mémorable"}])
    hits, total = search_logs(tmp_path, extract_terms("soiree"))
    assert total == 1 and hits[0].content == "Une SOIRÉE mémorable"


def test_terms_are_anded(logs):
    _, total = search_logs(logs, ["bachelier", "mention"])
    assert total == 1


def test_no_match_in_middle_of_word(tmp_path):
    _write(tmp_path, "salon", "2026-07-01",
           [{"author": "A", "content": "on part en departure"}])
    _, total = search_logs(tmp_path, ["part"])
    assert total == 1  # « part » en début de mot
    _, total = search_logs(tmp_path, ["parture"])
    assert total == 0  # milieu de mot : pas de match


def test_dm_never_searched(logs):
    hits, _ = search_logs(logs, ["secret"])
    assert hits == []


def test_non_conversational_events_ignored(logs):
    hits, _ = search_logs(logs, ["bachelier"])
    assert all(h.author != "?" for h in hits)


# ── Filtres ──────────────────────────────────────────────────────────────────

def test_filter_by_author_name_partial(logs):
    hits, total = search_logs(logs, ["bachelier"], author="azrael")
    assert total == 2
    assert {h.author_id for h in hits} == {"111"}


def test_filter_by_author_id(logs):
    _, total = search_logs(logs, ["bachelier"], author="222")
    assert total == 1


def test_filter_by_channel_partial_and_accent_insensitive(logs):
    _, total = search_logs(logs, ["bachelier"], channel="shitpost")
    assert total == 1


def test_filter_by_date_range(logs):
    _, total = search_logs(
        logs, ["bachelier"], after=date(2026, 7, 1), before=date(2026, 7, 1)
    )
    assert total == 2  # le message de Bob + celui de Wally, ce jour-là


def test_filter_before_excludes_later_days(logs):
    hits, total = search_logs(logs, ["bachelier"], before=date(2026, 3, 31))
    assert total == 1 and hits[0].author_id == "111"


def test_limit_keeps_the_most_recent_in_chronological_order(logs):
    hits, total = search_logs(logs, ["bachelier"], limit=2)
    assert total == 4
    assert len(hits) == 2
    assert hits[0].ts < hits[1].ts
    assert hits[-1].channel == "Purgatoire_shitpost"  # le plus récent


# ── Robustesse ───────────────────────────────────────────────────────────────

def test_missing_root_returns_empty(tmp_path):
    assert search_logs(tmp_path / "nope", ["bachelier"]) == ([], 0)


def test_corrupt_lines_and_files_are_skipped(tmp_path):
    path = tmp_path / "discord" / "salon" / "2026-07-01.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "pas du json\n"
        '{"type": "message_in", "ts": 1.0}\n'          # sans content
        '{"type": "message_in", "content": "bachelier"}\n'  # sans ts
        '{"type": "message_in", "ts": 100.0, "content": "bachelier ok", "author": "A"}\n',
        encoding="utf-8",
    )
    # Un dossier daté n'importe comment ne doit pas faire tomber la recherche.
    bad = tmp_path / "discord" / "salon" / "pas-une-date.jsonl"
    bad.write_text('{"type": "message_in", "ts": 1.0, "content": "bachelier"}\n',
                   encoding="utf-8")
    hits, total = search_logs(tmp_path, ["bachelier"])
    assert total == 1 and hits[0].content == "bachelier ok"


# ── Service ──────────────────────────────────────────────────────────────────

def test_tool_definition_shape():
    fn = HISTORY_SEARCH_TOOL["function"]
    assert HISTORY_SEARCH_TOOL["type"] == "function"
    assert fn["name"] == "search_history"
    assert fn["parameters"]["required"] == ["query"]
    assert set(fn["parameters"]["properties"]) == {
        "query", "author", "channel", "after", "before", "limit",
    }


def test_available_reflects_logs_presence(tmp_path, logs):
    assert HistorySearchService(logs).available is True
    assert HistorySearchService(tmp_path / "vide").available is False


@pytest.mark.asyncio
async def test_search_renders_hits(logs):
    out = await HistorySearchService(logs).search("bachelier")
    assert "4 message(s) trouvé(s)" in out
    assert "#Purgatoire_general" in out
    assert "Azraël (@azrael)" in out
    assert "10/03/2026" in out


@pytest.mark.asyncio
async def test_search_reports_truncation(logs):
    out = await HistorySearchService(logs).search("bachelier", limit=2)
    assert "4 message(s) trouvé(s)" in out
    assert "les 2 plus récents" in out


@pytest.mark.asyncio
async def test_search_filters_are_echoed(logs):
    out = await HistorySearchService(logs).search("bachelier", author="azrael")
    assert "auteur: azrael" in out


@pytest.mark.asyncio
async def test_search_without_result_suggests_widening(logs):
    out = await HistorySearchService(logs).search("licorne")
    assert "Aucun message trouvé" in out


@pytest.mark.asyncio
async def test_search_rejects_empty_query(logs):
    out = await HistorySearchService(logs).search("  ?  ")
    assert "Recherche impossible" in out


@pytest.mark.asyncio
async def test_search_rejects_bad_date(logs):
    out = await HistorySearchService(logs).search("bachelier", after="hier")
    assert "Date invalide" in out and "after" in out


@pytest.mark.asyncio
async def test_search_rejects_inverted_range(logs):
    out = await HistorySearchService(logs).search(
        "bachelier", after="2026-07-01", before="2026-03-01"
    )
    assert "Plage de dates invalide" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,expected", [(0, 1), (999, 4), (None, 4), ("x", 4)])
async def test_search_clamps_limit(logs, limit, expected):
    out = await HistorySearchService(logs).search("bachelier", limit=limit)
    assert out.count("] #") == expected
    assert MAX_LIMIT >= DEFAULT_LIMIT


@pytest.mark.asyncio
async def test_search_never_raises_on_broken_root(tmp_path):
    out = await HistorySearchService(tmp_path / "nope").search("bachelier")
    assert "Aucun message trouvé" in out


# ── Le vocal du stream ───────────────────────────────────────────────────────

_STREAM = "𝗦𝗧𝗥𝗘𝗔𝗠"   # le vrai nom de dossier : des lettres « stylées »


def _write_voice(root, day: str, records: list[dict], channel: str = _STREAM) -> None:
    path = root / "voice" / channel / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            rec.setdefault("ts", _ts(day, 21))
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.fixture
def vocal(logs):
    """L'historique Discord + deux lives : l'ancien journal, puis `voice_line`."""
    # Avant le 2026-09-11 : seules les phrases qui l'ont déclenché ou frôlé.
    _write_voice(logs, "2026-09-07", [
        {"type": "message_in", "author": "Azraël (@azrael)", "author_id": "111",
         "content": "Wally, la clé du bachelier est là"},
        {"type": "message_out", "author": "Wally", "content": "prends-la vite"},
        {"type": "voice_near_miss", "speaker": "Rina (@rina)",
         "content": "mon bachelier de Wal", "word": "Wal"},
        {"type": "tool_called", "tool": "quote", "args": "bachelier"},
    ])
    # Depuis : tout en `voice_line`, et la même phrase aussi sous l'ancienne forme.
    _write_voice(logs, "2026-09-14", [
        {"type": "voice_line", "author": "Azraël (@azrael)",
         "content": "le bachelier  des cheaters"},
        {"type": "message_in", "author": "Azraël (@azrael)", "author_id": "111",
         "content": "le bachelier des cheaters"},
        {"type": "voice_line", "author": "Wally", "content": "un bachelier en carton"},
    ])
    return logs


def test_voice_lines_are_found_and_tagged(vocal):
    hits, _ = search_logs(vocal, ["cheaters"])
    assert [h.vocal for h in hits] == [True]
    assert hits[0].render().startswith("[14/09/2026 21h00] vocal 𝗦𝗧𝗥𝗘𝗔𝗠, Azraël (@azrael): ")


def test_legacy_voice_journal_stays_searchable(vocal):
    """Le passé d'avant `voice_line` : déclenchements, réponses, quasi-déclenchements."""
    hits, _ = search_logs(vocal, ["bachelier"], before=date(2026, 9, 7), after=date(2026, 9, 7))
    assert {h.content for h in hits} == {
        "Wally, la clé du bachelier est là", "mon bachelier de Wal",
    }


def test_near_miss_is_signed_by_its_speaker(vocal):
    hits, _ = search_logs(vocal, ["bachelier"], author="rina")
    assert [h.author for h in hits] == ["Rina (@rina)"]


def test_a_phrase_journaled_twice_is_returned_once(vocal):
    _, total = search_logs(vocal, ["cheaters"])
    assert total == 1


def test_wally_voice_lines_are_his(vocal):
    hits, _ = search_logs(vocal, ["carton"], author="wally")
    assert len(hits) == 1 and hits[0].vocal


def test_stylized_channel_names_match_plain_letters(vocal):
    _, total = search_logs(vocal, ["bachelier"], channel="stream")
    assert total == 4   # 2 du vieux journal + 2 `voice_line`


def test_voice_only_never_reads_discord(vocal):
    hits, total = search_logs(vocal, ["bachelier"], sources=("voice",))
    assert total == 4 and all(h.vocal for h in hits)


def test_voice_tool_keeps_the_same_name_and_parameters():
    fn = VOICE_HISTORY_SEARCH_TOOL["function"]
    assert fn["name"] == HISTORY_SEARCH_TOOL["function"]["name"]
    assert fn["parameters"] == HISTORY_SEARCH_TOOL["function"]["parameters"]
    assert "Discord" not in fn["description"]


def test_voice_journal_alone_makes_the_service_available(tmp_path):
    _write_voice(tmp_path, "2026-09-14", [{"type": "voice_line", "author": "A", "content": "x"}])
    svc = HistorySearchService(tmp_path)
    assert svc.available and svc.voice_available


@pytest.mark.asyncio
async def test_search_warns_that_voice_is_a_transcription(vocal):
    out = await HistorySearchService(vocal).search("cheaters")
    assert "transcriptions automatiques" in out
    out = await HistorySearchService(vocal).search("mention")
    assert "transcriptions automatiques" not in out


@pytest.mark.asyncio
async def test_voice_only_search_hides_discord(vocal):
    out = await HistorySearchService(vocal).search("bachelier", voice_only=True)
    assert "4 message(s) trouvé(s)" in out
    assert "#Purgatoire" not in out


# ── Le périmètre se décide chez l'APPELANT ───────────────────────────────────

@pytest.mark.asyncio
async def test_twitch_executor_never_reaches_discord(vocal):
    """Le chat est public : même si le modèle réclame un salon Discord, rien ne sort."""
    from types import SimpleNamespace

    from bot.twitch.handlers import make_tool_executor

    bot = SimpleNamespace(history_search=HistorySearchService(vocal))
    executor = make_tool_executor(bot, platform="twitch", user_id="1", author="viewer",
                                  channel="azrael_ttv")
    out = await executor("search_history", json.dumps({"query": "bachelier"}))
    assert "vocal 𝗦𝗧𝗥𝗘𝗔𝗠" in out and "#Purgatoire" not in out
    out = await executor("search_history",
                         json.dumps({"query": "bachelier", "channel": "general"}))
    assert "Aucun message trouvé" in out


@pytest.mark.asyncio
async def test_twitch_executor_refuses_from_a_guest_channel(vocal):
    from types import SimpleNamespace

    from bot.twitch.handlers import make_tool_executor

    bot = SimpleNamespace(history_search=HistorySearchService(vocal))
    executor = make_tool_executor(bot, platform="twitch", user_id="1", author="viewer",
                                  channel="un_invite", overlay=False)
    out = await executor("search_history", json.dumps({"query": "bachelier"}))
    assert "pas consultable" in out


@pytest.mark.asyncio
async def test_voice_executor_narrows_to_voice_when_broadcast(vocal, monkeypatch):
    """En conversation vocale, tout ; dans le salon diffusé, sa réponse part au
    stream — le vocal seul, comme au chat Twitch."""
    from types import SimpleNamespace

    import bot.core.voice_transcript as vt
    from bot.discord.voice.tools import make_voice_tool_executor

    bot = SimpleNamespace(history_search=HistorySearchService(vocal))
    service = SimpleNamespace(channel_id=4242)
    executor = make_voice_tool_executor(bot, service, lambda: None)
    args = json.dumps({"query": "bachelier"})

    monkeypatch.setattr(vt, "voice_is_broadcast", lambda cid: False)
    assert "#Purgatoire" in await executor("search_history", args)

    monkeypatch.setattr(vt, "voice_is_broadcast", lambda cid: cid == 4242)
    assert "#Purgatoire" not in await executor("search_history", args)


# ── Câblage dans le pipeline Discord ─────────────────────────────────────────

async def _offered_tools(bot, message):
    """Outils réellement proposés au LLM pour ce message."""
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    return bot.llm.complete_with_tools.call_args.args[2]


@pytest.mark.asyncio
async def test_tool_offered_when_history_available(logs):
    bot = make_bot()
    bot.history_search = HistorySearchService(logs)
    tools = await _offered_tools(bot, make_message(content="wally et le bachelier ?"))
    assert any(t["function"]["name"] == "search_history" for t in tools)


@pytest.mark.asyncio
async def test_tool_not_offered_without_logs(tmp_path):
    bot = make_bot()
    bot.history_search = HistorySearchService(tmp_path / "vide")
    tools = await _offered_tools(bot, make_message(content="wally et le bachelier ?"))
    assert not any(t["function"]["name"] == "search_history" for t in tools)


@pytest.mark.asyncio
async def test_executor_runs_the_search_with_filters(logs):
    bot = make_bot()
    bot.history_search = HistorySearchService(logs)
    message = make_message(content="wally et le bachelier ?")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    executor = bot.llm.complete_with_tools.call_args.args[3]

    result = await executor(
        "search_history",
        json.dumps({"query": "bachelier", "author": "azrael", "limit": 5}),
    )
    assert "2 message(s) trouvé(s)" in result
    assert "auteur: azrael" in result


@pytest.mark.asyncio
async def test_executor_refuses_when_history_unavailable(tmp_path):
    """Le modèle hallucine parfois un outil non offert : pas d'exception."""
    bot = make_bot()
    bot.history_search = HistorySearchService(tmp_path / "vide")
    message = make_message(content="wally et le bachelier ?")
    with patch("bot.discord.handlers.asyncio.create_task"):
        await _respond(bot, message, "12345", "99999", [])
    executor = bot.llm.complete_with_tools.call_args.args[3]

    result = await executor("search_history", json.dumps({"query": "bachelier"}))
    assert "pas consultable" in result
