import time
import hashlib
import pytest
from bot.dashboard.routes.chat_auth import create_jwt, decode_jwt, hash_token


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
