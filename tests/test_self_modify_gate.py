# tests/test_self_modify_gate.py
"""
Tests for WallyDiscord._self_modify_allowed() staticmethod.
Validates that SelfFix/SelfUpgrade are only wired when:
  - bridge_socket and bridge_secret are present
  - cognitive_loop is not None
  - config.bot.self_modify_enabled is True
  - config.bot.owner_discord_id is a non-empty string
"""
from types import SimpleNamespace


def test_self_modify_gate():
    from bot.discord.bot import WallyDiscord

    cfg_on = SimpleNamespace(self_modify_enabled=True, owner_discord_id="610")
    cfg_off = SimpleNamespace(self_modify_enabled=False, owner_discord_id="610")
    cfg_no_owner = SimpleNamespace(self_modify_enabled=True, owner_discord_id="")

    # All conditions met → allowed
    assert WallyDiscord._self_modify_allowed("sock", "secret", object(), cfg_on) is True

    # Flag disabled → denied
    assert WallyDiscord._self_modify_allowed("sock", "secret", object(), cfg_off) is False

    # No owner → denied
    assert WallyDiscord._self_modify_allowed("sock", "secret", object(), cfg_no_owner) is False

    # No bridge socket → denied
    assert WallyDiscord._self_modify_allowed("", "secret", object(), cfg_on) is False

    # cognitive_loop is None → denied
    assert WallyDiscord._self_modify_allowed("sock", "secret", None, cfg_on) is False
