# tests/test_dashboard_logs.py
"""Tests pour l'endpoint /api/admin/logs/history et les helpers de parsing."""
import pytest
from pathlib import Path

from bot.dashboard.routes.sse import _parse_log_line, _find_latest_log


# ── _parse_log_line ───────────────────────────────────────────────────────────

def test_parse_valid_info_line():
    line = "14:32:05 | INFO     | bot.discord.handlers:82 | Response sent to KingsRequin"
    result = _parse_log_line(line)
    assert result is not None
    assert result["time"] == "14:32:05"
    assert result["level"] == "INFO"
    assert result["message"] == "Response sent to KingsRequin"


def test_parse_valid_warning_line():
    line = "09:01:00 | WARNING  | bot.core.memory:106 | mem0 add failed: timeout"
    result = _parse_log_line(line)
    assert result is not None
    assert result["level"] == "WARNING"
    assert "mem0 add failed" in result["message"]


def test_parse_valid_error_line():
    line = "23:59:59 | ERROR    | bot.core.openai_client:55 | OpenAI call failed"
    result = _parse_log_line(line)
    assert result is not None
    assert result["level"] == "ERROR"


def test_parse_ignores_non_log_lines():
    """Lignes sans niveau connu (ex: lignes de continuation) → None."""
    assert _parse_log_line("") is None
    assert _parse_log_line("traceback (most recent call last)") is None
    assert _parse_log_line("  File bot/core/memory.py, line 42") is None


def test_parse_handles_pipe_in_message():
    """Le message peut contenir des | — seuls les 4 premiers champs sont splitpés."""
    line = "10:00:00 | INFO     | bot.main:10 | url=http://host:8080/path | extra"
    result = _parse_log_line(line)
    assert result is not None
    assert "url=http://host:8080/path | extra" in result["message"]


# ── _find_latest_log ──────────────────────────────────────────────────────────

def test_find_latest_log_returns_most_recent(tmp_path, monkeypatch):
    """Retourne le app.log le plus récemment modifié parmi les sous-dossiers."""
    import time as time_mod

    # Créer deux faux dossiers de log avec des timestamps différents
    old_dir = tmp_path / "2026-03-16"
    old_dir.mkdir()
    new_dir = tmp_path / "2026-03-17"
    new_dir.mkdir()

    old_log = old_dir / "app.log"
    new_log = new_dir / "app.log"
    old_log.write_text("old log content")
    new_log.write_text("new log content")

    # S'assurer que new_log a un mtime plus récent
    now = time_mod.time()
    import os
    os.utime(old_log, (now - 3600, now - 3600))
    os.utime(new_log, (now, now))

    # Patcher Path("logs") → tmp_path
    import bot.dashboard.routes.sse as sse_module
    original_path = sse_module.Path

    class PatchedPath(type(tmp_path)):
        def __new__(cls, *args):
            if args == ("logs",):
                return tmp_path
            return original_path(*args)

    monkeypatch.setattr(sse_module, "Path", PatchedPath)
    result = _find_latest_log()
    assert result is not None
    assert result.read_text() == "new log content"


def test_find_latest_log_returns_none_when_no_logs(tmp_path, monkeypatch):
    """Retourne None si aucun app.log n'existe."""
    import bot.dashboard.routes.sse as sse_module
    original_path = sse_module.Path

    class PatchedPath(type(tmp_path)):
        def __new__(cls, *args):
            if args == ("logs",):
                return tmp_path
            return original_path(*args)

    monkeypatch.setattr(sse_module, "Path", PatchedPath)
    result = _find_latest_log()
    assert result is None
