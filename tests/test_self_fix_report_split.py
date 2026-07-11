"""Le compte rendu de redéploiement de Claude Code est découpé en plusieurs
messages Discord ≤ 2000 caractères au lieu d'être tronqué."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.discord.message_split import DISCORD_MAX_LEN, split_for_discord
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


@pytest.mark.asyncio
async def test_deploy_report_is_chunked_not_truncated():
    dm = _FakeDM()
    bridge = SimpleNamespace(
        claude_run=AsyncMock(return_value="job-1"),
        claude_commit=AsyncMock(),
        git_push=AsyncMock(return_value={"pushed": True, "remote": "public",
                                         "branch": "main"}),
        docker_rebuild=AsyncMock(),
    )
    sf = SelfFix(bridge=bridge, bot=_make_bot(dm))

    long_result = ("Ligne de compte rendu détaillée du redéploiement. " * 120).strip()
    assert len(long_result) > DISCORD_MAX_LEN

    sf._await_reaction = AsyncMock(return_value="✅")
    sf._poll = AsyncMock(return_value={"state": "done", "changed": True,
                                       "result": long_result})

    await sf._run_upgrade(goal="corriger le bug X", norm="corriger le bug x")

    # Aucun message envoyé ne dépasse la limite Discord.
    assert all(len(m) <= DISCORD_MAX_LEN for m in dm.sent)
    # Le compte rendu occupe > 1 message (il a bien été découpé).
    report_parts = [m for m in dm.sent if "C'est implémenté et déployé" in m or
                    "compte rendu" in m.lower()]
    assert len(report_parts) >= 2
    # Rien n'a été tronqué : la marque de troncature n'apparaît nulle part…
    assert not any("tronqué" in m for m in dm.sent)
    # …et le texte complet du résultat est reconstituable depuis les morceaux.
    joined = "\n".join(dm.sent)
    assert long_result[-60:] in joined


@pytest.mark.asyncio
async def test_short_deploy_report_stays_single_message():
    dm = _FakeDM()
    bridge = SimpleNamespace(
        claude_run=AsyncMock(return_value="job-1"),
        claude_commit=AsyncMock(),
        git_push=AsyncMock(return_value={"pushed": True, "remote": "public",
                                         "branch": "main"}),
        docker_rebuild=AsyncMock(),
    )
    sf = SelfFix(bridge=bridge, bot=_make_bot(dm))

    sf._await_reaction = AsyncMock(return_value="✅")
    sf._poll = AsyncMock(return_value={"state": "done", "changed": True,
                                       "result": "Fait, tout est vert."})

    await sf._run_upgrade(goal="mini fix", norm="mini fix")

    report_parts = [m for m in dm.sent if "C'est implémenté et déployé" in m]
    assert len(report_parts) == 1
    assert report_parts[0] == split_for_discord(report_parts[0])[0]
