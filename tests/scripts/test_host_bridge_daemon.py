import json
import importlib
import os
from unittest.mock import patch
from scripts import host_bridge_daemon as d


def test_extract_claude_result_parses_json_result():
    raw = json.dumps({"type": "result", "result": "J'ai ajouté la lecture des réactions."})
    assert d._extract_claude_result(raw) == "J'ai ajouté la lecture des réactions."


def test_extract_claude_result_falls_back_to_tail_on_garbage():
    raw = "boom not json\n" * 5
    out = d._extract_claude_result(raw)
    assert "boom not json" in out


def test_extract_claude_result_empty():
    assert d._extract_claude_result("") == ""


def _parse_allowed_services(env_value: str) -> set:
    """Extrait la logique de parsing de ALLOWED_SERVICES pour la tester isolément."""
    return set(
        s.strip() for s in env_value.split(",") if s.strip()
    )


def test_allowed_services_default_is_wally():
    """Sans env ALLOWED_SERVICES, le set par défaut contient uniquement 'wally'."""
    result = _parse_allowed_services(os.environ.get("ALLOWED_SERVICES", "wally"))
    assert result == {"wally"}


def test_allowed_services_multi_value():
    """ALLOWED_SERVICES='wally,cindy' → {'wally', 'cindy'}."""
    result = _parse_allowed_services("wally,cindy")
    assert result == {"wally", "cindy"}


def test_allowed_services_strips_whitespace():
    """ALLOWED_SERVICES=' wally , cindy ' → {'wally', 'cindy'} (espaces ignorés)."""
    result = _parse_allowed_services(" wally , cindy ")
    assert result == {"wally", "cindy"}


def test_allowed_services_single_entry():
    """ALLOWED_SERVICES='cindy' → {'cindy'}."""
    result = _parse_allowed_services("cindy")
    assert result == {"cindy"}


def test_daemon_allowed_services_env_at_module_level():
    """Le module daemon charge ALLOWED_SERVICES depuis l'env au moment de l'import."""
    with patch.dict(os.environ, {"ALLOWED_SERVICES": "wally,cindy"}, clear=False):
        reloaded = importlib.reload(d)
        assert reloaded.ALLOWED_SERVICES == {"wally", "cindy"}
    # Recharge sans surcharge pour remettre l'état stable
    importlib.reload(d)
