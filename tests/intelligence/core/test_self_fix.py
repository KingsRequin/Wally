import asyncio
import types
import pytest
from unittest.mock import AsyncMock, MagicMock

OWNER_ID = "610550333042589752"


def _equip_owner(bot, owner=OWNER_ID, name="Wally", creator="KingsRequin"):
    """Équipe le mock bot d'un config exposant owner_discord_id, name, et creator_name."""
    bot.config = types.SimpleNamespace(
        bot=types.SimpleNamespace(owner_discord_id=owner, name=name, creator_name=creator)
    )
    return bot


def make_fix(approval="✅", status_seq=None):
    """Build a SelfFix with mocked bridge + bot. Default: approval ✅, job done+changed."""
    from bot.intelligence.self_fix import SelfFix

    bridge = MagicMock()
    bridge.claude_run = AsyncMock(return_value="job123")
    if status_seq is None:
        status_seq = [{"state": "done", "exit_code": 0, "result": "fait",
                       "changed": True, "head_changed": False, "output_tail": ""}]
    bridge.claude_status = AsyncMock(side_effect=status_seq)
    bridge.claude_commit = AsyncMock(return_value={"committed": True, "hash": "abc"})
    bridge.docker_rebuild = AsyncMock()

    bot = MagicMock()
    _equip_owner(bot)
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 7
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)
    # Mémoire de Wally : fact_store mockable pour vérifier le writeback d'issue.
    bot.memory.fact_store.add = AsyncMock(return_value=1)

    reaction = MagicMock()
    reaction.emoji = approval
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    fixer = SelfFix(bridge, bot, poll_interval=0.0)
    return fixer, bridge, bot, dm


def req(goal="voir les réactions emoji"):
    from bot.intelligence.self_fix import UpgradeRequest
    return UpgradeRequest(goal=goal)


@pytest.mark.asyncio
async def test_approval_runs_claude_then_rebuilds():
    fixer, bridge, bot, dm = make_fix(approval="✅")
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_called_once()
    # le goal est préfixé d'un préambule d'ingénierie, mais doit le contenir
    sent = bridge.claude_run.call_args[0][0]
    assert "voir les réactions emoji" in sent
    assert "vérifie l'état RÉEL du code" in sent  # préambule présent
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_refusal_does_not_run_claude_and_records_decline():
    fixer, bridge, bot, dm = make_fix(approval="❌")
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()
    bridge.docker_rebuild.assert_not_called()
    # second identical request is ignored (declined)
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()


@pytest.mark.asyncio
async def test_force_bypasses_declined():
    """Demande explicite du créateur (force=True) → outrepasse un refus précédent."""
    fixer, bridge, bot, dm = make_fix(approval="❌")
    await fixer.request_upgrade(req())  # refusé → goal mémorisé dans _declined
    bridge.claude_run.assert_not_called()
    # même goal, mais cette fois c'est le créateur qui demande explicitement
    bot.wait_for = AsyncMock(return_value=_approval_reaction())
    await fixer.request_upgrade(req(), force=True)
    bridge.claude_run.assert_called_once()


def _approval_reaction():
    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = 7
    user = MagicMock()
    user.id = int(OWNER_ID)
    return (reaction, user)


@pytest.mark.asyncio
async def test_timeout_cancels_without_running():
    fixer, bridge, bot, dm = make_fix()
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()
    assert dm.send.call_count >= 2  # proposal + cancellation


@pytest.mark.asyncio
async def test_claude_failure_notifies_no_rebuild():
    seq = [{"state": "failed", "exit_code": 1, "result": "", "changed": False,
            "head_changed": False, "output_tail": "boom"}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_not_called()
    assert any("échou" in c.args[0].lower() for c in dm.send.call_args_list)


@pytest.mark.asyncio
async def test_no_change_no_rebuild():
    seq = [{"state": "done", "exit_code": 0, "result": "rien", "changed": False,
            "head_changed": False, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_head_changed_triggers_rebuild():
    seq = [{"state": "done", "exit_code": 0, "result": "committed", "changed": False,
            "head_changed": True, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    bridge.docker_rebuild.assert_called_once_with("wally")


@pytest.mark.asyncio
async def test_empty_goal_is_ignored():
    fixer, bridge, bot, dm = make_fix()
    await fixer.request_upgrade(req(goal="   "))
    bot.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_progress_message_edited_during_run():
    """Un message d'avancement est édité au fil des polls 'running'."""
    seq = [{"state": "running"}, {"state": "running"},
           {"state": "done", "exit_code": 0, "result": "ok", "changed": True,
            "head_changed": False, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    msg = dm.send.return_value  # même mock renvoyé pour chaque dm.send
    assert msg.edit.await_count >= 1
    # le contenu d'au moins une édition mentionne un pourcentage
    assert any("%" in c.kwargs.get("content", "") for c in msg.edit.await_args_list)


@pytest.mark.asyncio
async def test_polls_until_terminal():
    seq = [{"state": "running"}, {"state": "running"},
           {"state": "done", "exit_code": 0, "result": "ok", "changed": True,
            "head_changed": False, "output_tail": ""}]
    fixer, bridge, bot, dm = make_fix(status_seq=seq)
    await fixer.request_upgrade(req())
    assert bridge.claude_status.call_count == 3
    bridge.docker_rebuild.assert_called_once()


@pytest.mark.asyncio
async def test_deploy_records_outcome_in_memory():
    """Après un déploiement réussi, Wally écrit en mémoire (wally:self) que le
    code_fix est accepté+déployé. Sans ça, son goal reste 'en attente
    d'autorisation' et il rumine la demande indéfiniment."""
    fixer, bridge, bot, dm = make_fix(approval="✅")
    await fixer.request_upgrade(req(goal="voir la présence en ligne"))
    store = bot.memory.fact_store
    assert store.add.await_count >= 1
    facts = [c.args[0] for c in store.add.await_args_list]
    assert all(f.user_id == "wally:self" for f in facts)
    blob = " ".join(f.content.lower() for f in facts)
    assert "présence en ligne" in blob  # le goal est rappelé
    assert "déploy" in blob              # l'issue finale est consignée


@pytest.mark.asyncio
async def test_refusal_records_outcome_in_memory():
    """Un refus est aussi consigné en mémoire pour que Wally cesse d'attendre."""
    fixer, bridge, bot, dm = make_fix(approval="❌")
    await fixer.request_upgrade(req(goal="un truc inutile"))
    store = bot.memory.fact_store
    facts = [c.args[0] for c in store.add.await_args_list]
    assert any(f.user_id == "wally:self" and "refus" in f.content.lower()
               for f in facts)


@pytest.mark.asyncio
async def test_timeout_records_outcome_in_memory():
    """Un timeout d'autorisation est consigné (demande en suspens, plus en attente active)."""
    fixer, bridge, bot, dm = make_fix()
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())
    await fixer.request_upgrade(req(goal="encore un truc"))
    store = bot.memory.fact_store
    facts = [c.args[0] for c in store.add.await_args_list]
    assert any(f.user_id == "wally:self" for f in facts)


@pytest.mark.asyncio
async def test_owner_id_read_from_config_not_constant():
    """_owner_id() doit lire config.bot.owner_discord_id, pas la constante module."""
    from bot.intelligence.self_fix import SelfFix

    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, owner="999888777666555444")

    fixer = SelfFix(bridge, bot, poll_interval=0.0)
    assert fixer._owner_id() == "999888777666555444"


@pytest.mark.asyncio
async def test_empty_owner_skips_run_upgrade():
    """Si owner_discord_id est vide dans config, _run_upgrade ne fait rien (early-return)."""
    from bot.intelligence.self_fix import SelfFix, UpgradeRequest

    bridge = MagicMock()
    bridge.claude_run = AsyncMock(return_value="job123")
    bridge.docker_rebuild = AsyncMock()
    bot = MagicMock()
    _equip_owner(bot, owner="")
    bot.memory.fact_store.add = AsyncMock(return_value=1)

    fixer = SelfFix(bridge, bot, poll_interval=0.0)
    await fixer.request_upgrade(UpgradeRequest(goal="fix something"))
    bridge.claude_run.assert_not_called()
    bot.fetch_user.assert_not_called()


@pytest.mark.asyncio
async def test_reaction_check_uses_config_owner():
    """_await_reaction.check compare user.id à config.bot.owner_discord_id, pas la constante."""
    fixer, bridge, bot, dm = make_fix(approval="✅")
    # Changer l'owner dans config vers un ID différent : la réaction du user original doit
    # être rejetée (wait_for lève TimeoutError) → claude_run ne doit pas être appelé.
    bot.config.bot.owner_discord_id = "111222333444555666"
    # wait_for simule un timeout car le check va rejeter le user (id != 111222333444555666)
    bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError())
    await fixer.request_upgrade(req())
    bridge.claude_run.assert_not_called()


@pytest.mark.asyncio
async def test_preamble_contains_bot_name():
    """Le goal envoyé au LLM via claude_run doit contenir le nom du bot rendu (pas «{{BOT_NAME}}»)."""
    import bot.intelligence.identity as identity
    identity._NAME = "Wally"  # reset pour isoler le test
    fixer, bridge, bot_mock, dm = make_fix(approval="✅")
    await fixer.request_upgrade(req(goal="voir les réactions emoji"))
    sent = bridge.claude_run.call_args[0][0]
    assert "{{BOT_NAME}}" not in sent
    assert "Wally" in sent


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_dispatches_to_self_fix():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.request_upgrade = AsyncMock()
    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(action="ACT", act_name="code_fix",
                            act_args={"goal": "voir les réactions emoji"})
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)
    self_fix_mock.request_upgrade.assert_called_once()


@pytest.mark.asyncio
async def test_action_dispatcher_code_fix_ignores_empty_goal():
    from bot.intelligence.action_dispatcher import ActionDispatcher
    from bot.intelligence.meta_agent import MetaDecision

    self_fix_mock = MagicMock()
    self_fix_mock.request_upgrade = AsyncMock()
    bot = MagicMock()
    bot.self_fix = self_fix_mock

    dispatcher = ActionDispatcher(bot=bot)
    decision = MetaDecision(action="ACT", act_name="code_fix", act_args={"goal": ""})
    await dispatcher.dispatch(decision)
    await asyncio.sleep(0)
    self_fix_mock.request_upgrade.assert_not_called()


def test_service_returns_wally_lowercase_by_default():
    """_service() retourne 'wally' quand config.bot.name='Wally'."""
    from bot.intelligence.self_fix import SelfFix

    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, name="Wally")

    fixer = SelfFix(bridge, bot)
    assert fixer._service() == "wally"


def test_service_returns_cindy_lowercase_when_name_cindy():
    """_service() retourne 'cindy' quand config.bot.name='Cindy'."""
    from bot.intelligence.self_fix import SelfFix

    bridge = MagicMock()
    bot = MagicMock()
    _equip_owner(bot, name="Cindy")

    fixer = SelfFix(bridge, bot)
    assert fixer._service() == "cindy"


@pytest.mark.asyncio
async def test_approval_runs_claude_then_rebuilds_cindy_service():
    """Avec config.bot.name='Cindy', docker_rebuild est appelé avec 'cindy'."""
    from bot.intelligence.self_fix import SelfFix, UpgradeRequest

    bridge = MagicMock()
    bridge.claude_run = AsyncMock(return_value="job456")
    bridge.claude_status = AsyncMock(return_value={
        "state": "done", "exit_code": 0, "result": "fait",
        "changed": True, "head_changed": False, "output_tail": "",
    })
    bridge.claude_commit = AsyncMock(return_value={"committed": True, "hash": "abc"})
    bridge.docker_rebuild = AsyncMock()

    bot = MagicMock()
    _equip_owner(bot, name="Cindy")
    dm = AsyncMock()
    msg = AsyncMock()
    msg.id = 8
    dm.send = AsyncMock(return_value=msg)
    msg.add_reaction = AsyncMock()
    owner = AsyncMock()
    owner.create_dm = AsyncMock(return_value=dm)
    bot.fetch_user = AsyncMock(return_value=owner)
    bot.memory.fact_store.add = AsyncMock(return_value=1)

    reaction = MagicMock()
    reaction.emoji = "✅"
    reaction.message.id = msg.id
    user = MagicMock()
    user.id = int(OWNER_ID)
    bot.wait_for = AsyncMock(return_value=(reaction, user))

    fixer = SelfFix(bridge, bot, poll_interval=0.0)
    await fixer.request_upgrade(UpgradeRequest(goal="améliorer quelque chose"))

    bridge.docker_rebuild.assert_called_once_with("cindy")


@pytest.mark.asyncio
async def test_outcome_uses_config_creator_name_not_constant():
    """Les messages d'outcome doivent utiliser creator_name() (config) au lieu du hardcoded 'KingsRequin'."""
    import bot.intelligence.identity as identity

    fixer, bridge, bot, dm = make_fix(approval="✅")
    # Changer le creator_name dans config vers "Bob"
    bot.config.bot.creator_name = "Bob"
    # Réinitialiser l'identité avec la nouvelle valeur
    identity.set_identity(bot.config.bot)

    await fixer.request_upgrade(req(goal="tester le nom du créateur"))

    store = bot.memory.fact_store
    facts = [c.args[0] for c in store.add.await_args_list]
    blob = " ".join(f.content.lower() for f in facts)

    # Vérifier que "Bob" est présent et non "KingsRequin"
    assert "bob" in blob, f"Creator name 'Bob' not found in outcome. Content: {blob}"
    assert "kingsrequin" not in blob, f"Hardcoded 'KingsRequin' should not appear. Content: {blob}"
