import asyncio

import pytest

from bot.intelligence.self_fix import SelfFix, UpgradeRequest
from bot.intelligence.owner_outreach import OwnerOutreachGate


class _DM:
    id = 1

    def __init__(self):
        self.sent = []

    async def send(self, content):
        self.sent.append(content)
        return _Msg()


class _Msg:
    id = 1

    async def add_reaction(self, e):
        pass


class _Owner:
    async def create_dm(self):
        return _DM()


class _Bot:
    class config:
        class bot:
            owner_discord_id = "42"
            name = "wally"

    async def fetch_user(self, uid):
        return _Owner()

    memory = None


@pytest.mark.asyncio
async def test_blocked_gate_defers_without_dm():
    gate = OwnerOutreachGate()
    gate.mark_sent()  # déjà un fil en attente
    sf = SelfFix(bridge=None, bot=_Bot(), gate=gate)
    # request_upgrade doit court-circuiter sans DM ni blacklist
    await sf.request_upgrade(UpgradeRequest(goal="ajouter X"))
    assert "ajouter x" not in sf._declined


@pytest.mark.asyncio
async def test_no_response_does_not_blacklist():
    # _await_reaction expire immédiatement → on vérifie : pas de blacklist, statut deferred
    gate = OwnerOutreachGate()
    sf = SelfFix(bridge=None, bot=_Bot(), gate=gate)

    async def _expire(msg, timeout):
        raise asyncio.TimeoutError

    sf._await_reaction = _expire  # type: ignore

    await sf.request_upgrade(UpgradeRequest(goal="ajouter Y"))
    assert "ajouter y" not in sf._declined
