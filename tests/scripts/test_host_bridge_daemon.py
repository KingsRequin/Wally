import json
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
