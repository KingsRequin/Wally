# tests/test_dashboard_emotion_api.py
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from bot.dashboard.routes.emotions import public_router, admin_router, _enrich_emotions


@pytest.fixture
def app_with_emotion():
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    mock_emotion = MagicMock()
    mock_emotion.get_state.return_value = {
        "anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45
    }
    mock_emotion.get_mood.return_value = {
        "anger": 0.40, "joy": 0.10, "sadness": 0.02, "curiosity": 0.55, "boredom": 0.15
    }
    mock_emotion.get_fatigue.return_value = {"anger": 0.43}
    mock_emotion.get_secondary_emotions.return_value = [("frustration", 0.45)]
    app.state.wally = MagicMock()
    app.state.wally.emotion = mock_emotion
    return TestClient(app)


def test_get_emotions_includes_mood_fatigue_secondaries(app_with_emotion):
    r = app_with_emotion.get("/api/public/emotions")
    assert r.status_code == 200
    data = r.json()
    assert "mood" in data
    assert data["mood"]["anger"] == pytest.approx(0.40)
    assert "fatigue" in data
    assert data["fatigue"]["anger"] == pytest.approx(0.43)
    assert "secondaries" in data
    assert data["secondaries"] == [["frustration", 0.45]]


def test_get_emotions_empty_fatigue_returns_empty_dict(app_with_emotion):
    app_with_emotion.app.state.wally.emotion.get_fatigue.return_value = {}
    r = app_with_emotion.get("/api/public/emotions")
    assert r.json()["fatigue"] == {}


def test_get_emotions_no_active_secondaries_returns_empty_list(app_with_emotion):
    app_with_emotion.app.state.wally.emotion.get_secondary_emotions.return_value = []
    r = app_with_emotion.get("/api/public/emotions")
    assert r.json()["secondaries"] == []


@pytest.fixture
def app_with_emotion_admin():
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/admin")
    mock_emotion = MagicMock()
    mock_emotion.get_state.return_value = {
        "anger": 0.65, "joy": 0.30, "sadness": 0.05, "curiosity": 0.50, "boredom": 0.45
    }
    mock_emotion.get_mood.return_value = {
        "anger": 0.40, "joy": 0.10, "sadness": 0.02, "curiosity": 0.55, "boredom": 0.15
    }
    mock_emotion.get_fatigue.return_value = {}
    mock_emotion.get_secondary_emotions.return_value = []
    app.state.wally = MagicMock()
    app.state.wally.emotion = mock_emotion
    return TestClient(app)


def test_admin_get_emotions_includes_mood_fatigue_secondaries(app_with_emotion_admin):
    """Admin endpoint /api/admin/emotions should include mood, fatigue, and secondaries."""
    r = app_with_emotion_admin.get("/api/admin/emotions")
    assert r.status_code == 200
    data = r.json()
    assert "mood" in data
    assert "fatigue" in data
    assert "secondaries" in data


def test_enrich_emotions_helper_directly():
    """Smoke test for _enrich_emotions — the function used by the SSE endpoint."""
    mock_engine = MagicMock()
    mock_engine.get_state.return_value = {
        "anger": 0.5, "joy": 0.2, "sadness": 0.1, "curiosity": 0.3, "boredom": 0.4
    }
    mock_engine.get_mood.return_value = {
        "anger": 0.2, "joy": 0.1, "sadness": 0.05, "curiosity": 0.15, "boredom": 0.1
    }
    mock_engine.get_fatigue.return_value = {}
    mock_engine.get_secondary_emotions.return_value = []
    result = _enrich_emotions(mock_engine)
    assert set(result["mood"]) == {"anger", "joy", "sadness", "curiosity", "boredom"}
    assert result["fatigue"] == {}
    assert result["secondaries"] == []


def test_get_emotions_zero_fatigue_filtered_to_empty_dict(app_with_emotion):
    """When all fatigue values are 0.0, result should be {} not {"anger": 0.0}."""
    app_with_emotion.app.state.wally.emotion.get_fatigue.return_value = {"anger": 0.0, "joy": 0.0}
    r = app_with_emotion.get("/api/public/emotions")
    assert r.json()["fatigue"] == {}
