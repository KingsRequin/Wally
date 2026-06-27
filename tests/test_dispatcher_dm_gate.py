import pytest

from bot.intelligence.action_dispatcher import ActionDispatcher
from bot.intelligence.owner_outreach import OwnerOutreachGate


class _User:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

        class _S:
            channel = type("C", (), {"id": 1})()

        return _S()


class _Bot:
    def __init__(self, u):
        self._u = u

    class config:
        class bot:
            owner_discord_id = "42"

    async def fetch_user(self, uid):
        return self._u


@pytest.mark.asyncio
async def test_dm_suppressed_when_gate_blocked():
    user = _User()
    gate = OwnerOutreachGate()
    gate.mark_sent()
    d = ActionDispatcher(bot=_Bot(user), gate=gate)
    await d._dm("42", "coucou")
    assert user.sent == []   # rien envoyé


@pytest.mark.asyncio
async def test_dm_sent_marks_gate():
    user = _User()
    gate = OwnerOutreachGate()
    d = ActionDispatcher(bot=_Bot(user), gate=gate)
    d._last_dm_ts = 0.0   # neutralise le cooldown temporel
    await d._dm("42", "coucou")
    assert user.sent == ["coucou"]
    assert gate.is_blocked() is True
