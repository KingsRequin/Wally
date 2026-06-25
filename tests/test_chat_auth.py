import time
import hashlib
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.dashboard.routes.chat_auth import create_jwt, decode_jwt, hash_token, router as chat_auth_router

JWT_TEST_SECRET = "test-secret-256-bits-long-enough-for-hs256"


def _make_admin_token_client(owner_discord_id: str, dashboard_token: str = "admintoken") -> TestClient:
    """Monte une app minimale avec le router chat_auth et app.state.wally mocké."""
    app = FastAPI()
    app.include_router(chat_auth_router, prefix="/api/chat")

    cfg = MagicMock()
    cfg.bot.owner_discord_id = owner_discord_id
    cfg.bot.dashboard_token = dashboard_token

    wally = MagicMock()
    wally.config = cfg

    app.state.wally = wally

    import os
    os.environ["JWT_SECRET"] = JWT_TEST_SECRET

    return TestClient(app, raise_server_exceptions=False)


def _make_owner_jwt(discord_id: str) -> str:
    return create_jwt(discord_id, "Owner", None, JWT_TEST_SECRET)


# ── Tests admin-token owner via config ────────────────────────────────────────

def test_admin_token_owner_accepted():
    """L'owner configuré obtient le token admin."""
    client = _make_admin_token_client(owner_discord_id="111222333444555666")
    jwt_token = _make_owner_jwt("111222333444555666")
    r = client.get("/api/chat/auth/admin-token", headers={"Authorization": f"Bearer {jwt_token}"})
    assert r.status_code == 200
    assert r.json()["token"] == "admintoken"


def test_admin_token_non_owner_refused():
    """Un discord_id différent de l'owner reçoit 403."""
    client = _make_admin_token_client(owner_discord_id="111222333444555666")
    jwt_token = _make_owner_jwt("999888777666555444")
    r = client.get("/api/chat/auth/admin-token", headers={"Authorization": f"Bearer {jwt_token}"})
    assert r.status_code == 403


def test_admin_token_empty_owner_refused():
    """owner_discord_id vide ⇒ aucun accès accordé, même avec un JWT valide."""
    client = _make_admin_token_client(owner_discord_id="")
    jwt_token = _make_owner_jwt("111222333444555666")
    r = client.get("/api/chat/auth/admin-token", headers={"Authorization": f"Bearer {jwt_token}"})
    assert r.status_code == 403


def test_create_and_decode_jwt():
    secret = "test-secret-256-bits-long-enough-for-hs256"
    token = create_jwt("123", "Alice", "https://avatar", secret, ttl=3600)
    payload = decode_jwt(token, secret)
    assert payload["discord_id"] == "123"
    assert payload["username"] == "Alice"
    assert payload["avatar_url"] == "https://avatar"


def test_decode_jwt_expired():
    secret = "test-secret-256-bits-long-enough-for-hs256"
    token = create_jwt("123", "Alice", None, secret, ttl=-1)
    payload = decode_jwt(token, secret)
    assert payload is None


def test_decode_jwt_invalid():
    payload = decode_jwt("not.a.jwt", "secret")
    assert payload is None


def test_hash_token():
    h = hash_token("my-token")
    assert h == hashlib.sha256(b"my-token").hexdigest()
    assert len(h) == 64
