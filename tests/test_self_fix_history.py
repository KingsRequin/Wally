from types import SimpleNamespace
from unittest.mock import MagicMock
from bot.intelligence.self_fix import SelfFix


def test_remember_in_dm_appends_to_context_window():
    memory = MagicMock()
    bot = SimpleNamespace(memory=memory)
    sf = SelfFix(bridge=MagicMock(), bot=bot)
    dm = SimpleNamespace(id=4242)

    sf._remember_in_dm(dm, "[demande de self-fix] corriger le bug X")

    memory.append_message.assert_called_once()
    args, kwargs = memory.append_message.call_args
    assert args[0] == "4242"                              # channel_id = str(dm.id)
    assert "corriger le bug X" in args[2]                 # contenu injecté


def test_remember_in_dm_never_raises_without_memory():
    bot = SimpleNamespace(memory=None)
    sf = SelfFix(bridge=MagicMock(), bot=bot)
    sf._remember_in_dm(SimpleNamespace(id=1), "x")        # ne lève pas


def test_remember_in_dm_terminal_outcome_reaches_dm():
    """Vérifie que les issues terminales (refusé, échoué, déployé, …) sont bien
    injectées dans le fil DM via _remember_in_dm."""
    memory = MagicMock()
    bot = SimpleNamespace(memory=memory)
    sf = SelfFix(bridge=MagicMock(), bot=bot)
    dm = SimpleNamespace(id=9999)
    goal = "corriger le bug critique Y"

    for tag, expected_tag in [
        (f"[self-fix refusé] {goal}", "[self-fix refusé]"),
        (f"[self-fix abandonné — pas de réponse] {goal}", "[self-fix abandonné — pas de réponse]"),
        (f"[self-fix abandonné — Claude Code n'a pas répondu] {goal}", "[self-fix abandonné — Claude Code n'a pas répondu]"),
        (f"[self-fix échoué] {goal}", "[self-fix échoué]"),
        (f"[self-fix déployé] {goal}", "[self-fix déployé]"),
    ]:
        memory.reset_mock()
        sf._remember_in_dm(dm, tag)
        memory.append_message.assert_called_once()
        args, _ = memory.append_message.call_args
        assert args[0] == "9999", f"channel_id inattendu pour le tag {expected_tag!r}"
        assert expected_tag in args[2], f"tag manquant dans le message injecté : {args[2]!r}"
        assert goal in args[2], f"goal manquant dans le message injecté : {args[2]!r}"
