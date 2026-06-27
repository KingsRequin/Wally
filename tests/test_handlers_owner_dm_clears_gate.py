from bot.intelligence.owner_outreach import OwnerOutreachGate
from bot.discord.handlers import maybe_clear_owner_gate


class _Cfg:
    class bot:
        owner_discord_id = "42"


def test_owner_dm_clears_gate():
    gate = OwnerOutreachGate()
    gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="42", is_dm=True)
    assert gate.is_blocked() is False


def test_non_owner_dm_does_not_clear():
    gate = OwnerOutreachGate()
    gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="99", is_dm=True)
    assert gate.is_blocked() is True


def test_owner_guild_message_does_not_clear():
    gate = OwnerOutreachGate()
    gate.mark_sent()
    maybe_clear_owner_gate(gate, _Cfg, author_id="42", is_dm=False)
    assert gate.is_blocked() is True
