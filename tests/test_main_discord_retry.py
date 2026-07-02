"""Retry du login Discord au boot.

Une panne DNS/réseau transitoire (ex. l'hôte Proxmox qui redémarre) ne doit pas
laisser Wally en zombie : `_run_discord` réessaie le login avec backoff avant
d'abandonner, et ne connecte le websocket qu'une fois le login réussi.
"""
import asyncio

import pytest

from bot.main import _run_discord


async def _noop_sleep(*_a, **_k):
    return


class _FakeBot:
    """Bot minimal : login() échoue `fail_times` fois puis réussit."""

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.login_calls = 0
        self.connect_calls = 0
        self.connect_kwargs: dict | None = None

    async def login(self, token: str) -> None:
        self.login_calls += 1
        if self.login_calls <= self._fail_times:
            raise OSError("[Errno -3] Temporary failure in name resolution")

    async def connect(self, *, reconnect: bool = True) -> None:
        self.connect_calls += 1
        self.connect_kwargs = {"reconnect": reconnect}


async def test_retries_login_then_connects(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    bot = _FakeBot(fail_times=3)
    await _run_discord(bot, "tok", max_attempts=8, base_delay=0.01)
    assert bot.login_calls == 4          # 3 échecs + 1 succès
    assert bot.connect_calls == 1        # connexion une seule fois, après login OK
    assert bot.connect_kwargs == {"reconnect": True}


async def test_connects_immediately_when_login_ok(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    bot = _FakeBot(fail_times=0)
    await _run_discord(bot, "tok")
    assert bot.login_calls == 1
    assert bot.connect_calls == 1


async def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    bot = _FakeBot(fail_times=99)
    with pytest.raises(OSError):
        await _run_discord(bot, "tok", max_attempts=3, base_delay=0.01)
    assert bot.login_calls == 3
    assert bot.connect_calls == 0        # jamais connecté → le process pourra sortir


async def test_bad_token_is_not_retried(monkeypatch):
    """Une LoginFailure (token invalide) n'est pas une OSError → pas de retry."""
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    class _BadToken(_FakeBot):
        async def login(self, token: str) -> None:
            self.login_calls += 1
            raise RuntimeError("Improper token")

    bot = _BadToken(fail_times=0)
    with pytest.raises(RuntimeError):
        await _run_discord(bot, "tok", max_attempts=8, base_delay=0.01)
    assert bot.login_calls == 1          # une seule tentative
    assert bot.connect_calls == 0
