"""Tout selfix déployé est publié : après le commit, le flux pousse HEAD vers le
remote public, puis rebuild. Un échec de push ne bloque pas le déploiement local."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.intelligence.self_fix import SelfFix


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.id = 1

    async def add_reaction(self, emoji):
        pass

    async def edit(self, content):
        self.content = content


class _FakeDM:
    def __init__(self):
        self.id = 555
        self.sent: list[str] = []

    async def send(self, content):
        self.sent.append(content)
        return _FakeMessage(content)


class _FakeOwner:
    def __init__(self, dm):
        self._dm = dm

    async def create_dm(self):
        return self._dm


def _make_bot(dm):
    return SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="42", name="Wally")),
        memory=None,
        fetch_user=AsyncMock(return_value=_FakeOwner(dm)),
    )


def _prime(sf):
    sf._await_reaction = AsyncMock(return_value="✅")
    sf._poll = AsyncMock(return_value={"state": "done", "changed": True,
                                       "result": "Fait, tout est vert."})


@pytest.mark.asyncio
async def test_deploy_commits_then_pushes_then_rebuilds():
    dm = _FakeDM()
    calls: list[str] = []
    bridge = SimpleNamespace(
        claude_run=AsyncMock(return_value="job-1"),
        claude_commit=AsyncMock(side_effect=lambda *_: calls.append("commit")),
        git_push=AsyncMock(side_effect=lambda: calls.append("push") or
                           {"pushed": True, "remote": "public", "branch": "main"}),
        docker_rebuild=AsyncMock(side_effect=lambda *_: calls.append("build")),
    )
    sf = SelfFix(bridge=bridge, bot=_make_bot(dm))
    _prime(sf)

    await sf._run_upgrade(goal="mini fix", norm="mini fix")

    # Le selfix est bien publié, et dans l'ordre commit → push → build.
    assert calls == ["commit", "push", "build"]
    bridge.git_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_failure_does_not_block_rebuild():
    dm = _FakeDM()
    bridge = SimpleNamespace(
        claude_run=AsyncMock(return_value="job-1"),
        claude_commit=AsyncMock(),
        git_push=AsyncMock(side_effect=RuntimeError("remote injoignable")),
        docker_rebuild=AsyncMock(),
    )
    sf = SelfFix(bridge=bridge, bot=_make_bot(dm))
    _prime(sf)

    await sf._run_upgrade(goal="mini fix", norm="mini fix")

    # Push échoué mais le déploiement local (rebuild) a quand même eu lieu.
    bridge.git_push.assert_awaited_once()
    bridge.docker_rebuild.assert_awaited_once()
    # Et l'utilisateur reçoit tout de même le compte rendu de déploiement.
    assert any("C'est implémenté et déployé" in m for m in dm.sent)
