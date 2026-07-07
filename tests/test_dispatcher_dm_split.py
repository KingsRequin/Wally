import pytest

from bot.discord.message_split import DISCORD_MAX_LEN, split_for_discord
from bot.intelligence.action_dispatcher import ActionDispatcher


class _User:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, msg):
        self.sent.append(msg)
        return type("Msg", (), {"id": len(self.sent), "channel": None})()


class _Bot:
    def __init__(self, u):
        self._u = u

    class config:
        class bot:
            owner_discord_id = "42"

    async def fetch_user(self, uid):
        return self._u


@pytest.mark.asyncio
async def test_long_dm_split_into_multiple_messages():
    user = _User()
    d = ActionDispatcher(bot=_Bot(user))
    d._last_dm_ts = 0.0  # neutralise le cooldown temporel
    report = ("Rapport détaillé de la journée. " * 300).strip()
    assert len(report) > DISCORD_MAX_LEN

    await d._dm("42", report)

    assert len(user.sent) > 1
    assert all(len(m) <= DISCORD_MAX_LEN for m in user.sent)
    assert user.sent == split_for_discord(report)
