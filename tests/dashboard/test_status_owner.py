"""`/api/public/status` : ce qu'il publie, et ce qu'il ne publie plus.

Ces tests exigeaient que la route expose `owner_discord_id`. C'est justement le
défaut : la route est anonyme, et le snowflake réel du propriétaire partait à
tout visiteur pour une comparaison purement cosmétique côté client (afficher ou
non le bouton ADMIN). Le verdict est désormais signé dans le JWT (`is_owner`).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from bot.dashboard.routes import status


def _client(owner_discord_id: str, name: str) -> TestClient:
    app = FastAPI()
    app.include_router(status.router, prefix="/api/public")
    app.state.wally = SimpleNamespace(
        start_time=0.0,
        message_count=0,
        messages_avant_boot=0,
        message_count_discord=0,
        message_count_twitch=0,
        message_count_web=0,
        discord_bot=None,
        twitch_bot=None,
        avg_response_ms=None,
        config=SimpleNamespace(
            bot=SimpleNamespace(
                owner_discord_id=owner_discord_id,
                name=name,
            )
        ),
    )
    return TestClient(app)


def test_status_ne_publie_pas_l_identifiant_du_proprietaire():
    # Un identifiant improbable : « 42 » se retrouvait par hasard dans
    # `uptime_seconds`, ce qui rendait le test dépendant du moment.
    r = _client("987654321098765432", "Cindy").get("/api/public/status")
    assert r.status_code == 200
    corps = r.json()
    assert "owner_discord_id" not in corps
    assert "987654321098765432" not in str(corps)


def test_status_exposes_bot_name():
    r = _client("42", "Cindy").get("/api/public/status")
    assert r.status_code == 200
    assert r.json()["bot_name"] == "Cindy"


def test_le_snowflake_reel_ne_fuit_pas():
    """Le cas de production : l'identifiant du propriétaire de Wally."""
    r = _client("610550333042589752", "Wally").get("/api/public/status")
    assert r.status_code == 200
    data = r.json()
    assert "610550333042589752" not in str(data)
    assert data["bot_name"] == "Wally"      # ce qui reste public, lui, est utile
