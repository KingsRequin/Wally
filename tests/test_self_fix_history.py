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
