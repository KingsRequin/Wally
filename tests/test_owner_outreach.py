from bot.intelligence.owner_outreach import OwnerOutreachGate


def test_gate_blocks_after_sent_until_cleared():
    g = OwnerOutreachGate()
    assert g.is_blocked() is False
    g.mark_sent()
    assert g.is_blocked() is True
    g.clear()
    assert g.is_blocked() is False


def test_clear_when_not_blocked_is_safe():
    g = OwnerOutreachGate()
    g.clear()
    assert g.is_blocked() is False
