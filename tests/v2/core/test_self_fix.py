import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


OWNER_ID = "610550333042589752"
NON_OWNER_ID = "999999999999"


def make_fix(tmp_path: Path, llm_diff: str = "--- a/x\n+++ b/x\n"):
    from bot.v2.core.self_fix import SelfFix, FixRequest

    # create a real file in tmp_path
    src = tmp_path / "bot" / "core" / "emotion.py"
    src.parent.mkdir(parents=True)
    src.write_text("# original\n")

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_diff)

    bridge = MagicMock()
    bridge.git_apply = AsyncMock()
    bridge.docker_rebuild = AsyncMock()

    bot = MagicMock()
    owner = AsyncMock()
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 42
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)

    fixer = SelfFix(llm, bridge, bot, repo_root=str(tmp_path))
    req_owner = FixRequest(
        requester_discord_id=OWNER_ID,
        file_path="bot/core/emotion.py",
        description="fix the bug",
    )
    req_non_owner = FixRequest(
        requester_discord_id=NON_OWNER_ID,
        file_path="bot/core/emotion.py",
        description="fix",
    )
    return fixer, bridge, llm, dm, msg, bot, req_owner, req_non_owner


@pytest.mark.asyncio
async def test_fix_rejected_if_not_owner(tmp_path):
    fixer, bridge, llm, dm, msg, bot, _, req_non_owner = make_fix(tmp_path)
    await fixer.fix(req_non_owner)
    llm.complete.assert_not_called()
    bridge.git_apply.assert_not_called()


@pytest.mark.asyncio
async def test_fix_rejected_if_file_missing(tmp_path):
    fixer, bridge, llm, dm, msg, bot, _, _ = make_fix(tmp_path)
    from bot.v2.core.self_fix import FixRequest
    req = FixRequest(requester_discord_id=OWNER_ID, file_path="nonexistent.py", description="x")
    await fixer.fix(req)
    llm.complete.assert_not_called()
    bridge.git_apply.assert_not_called()


@pytest.mark.asyncio
async def test_fix_sends_dm_with_diff_preview(tmp_path):
    diff = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n"
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path, llm_diff=diff)
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    llm.complete.assert_called_once()
    dm.send.assert_called()
    sent_text = dm.send.call_args_list[0][0][0]
    assert "bot/core/emotion.py" in sent_text
    assert "diff" in sent_text.lower() or "---" in sent_text or diff[:20] in sent_text


@pytest.mark.asyncio
async def test_fix_applies_on_checkmark(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    bridge.git_apply.assert_called_once()
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_fix_cancels_on_cross(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    reaction = MagicMock()
    reaction.emoji = "❌"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    await fixer.fix(req_owner)

    bridge.git_apply.assert_not_called()
    bridge.docker_rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_fix_cancels_on_timeout(tmp_path):
    fixer, bridge, llm, dm, msg, bot, req_owner, _ = make_fix(tmp_path)
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())

    await fixer.fix(req_owner)

    bridge.git_apply.assert_not_called()
    # DM cancellation message sent
    assert dm.send.call_count >= 2  # initial preview + timeout msg


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_dispatches_to_self_fix():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.fix = AsyncMock()

    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(
        action="ACT",
        act_name="code_fix",
        act_args={
            "requester_discord_id": OWNER_ID,
            "file_path": "bot/core/emotion.py",
            "description": "fix the bug",
        },
    )
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)  # let create_task run

    self_fix_mock.fix.assert_called_once()


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_rejects_non_owner():
    from bot.v2.core.action_dispatcher import ActionDispatcher
    from bot.v2.core.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.fix = AsyncMock()

    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(
        action="ACT",
        act_name="code_fix",
        act_args={
            "requester_discord_id": NON_OWNER_ID,
            "file_path": "bot/core/emotion.py",
            "description": "fix",
        },
    )
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)

    self_fix_mock.fix.assert_not_called()
