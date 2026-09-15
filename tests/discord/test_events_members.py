"""Câblage `on_member_join` — défense en profondeur autour de la fiche de bienvenue.

`bienvenue.accueillir` ne lève jamais en théorie (son propre try/except large
couvre TOUT le corps de la fonction, cf. `tests/discord/test_bienvenue.py`),
mais l'event Discord ne doit JAMAIS dépendre de cette seule garantie : un
défaut malgré tout ne doit pas priver la perception cognitive
(`_member_join_context`) de l'arrivée.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.discord.events import members


def _bot_discord():
    """Capture le handler `on_member_join` enregistré via `@bot.event`."""
    bot = MagicMock()
    captured: dict = {}
    bot.event = lambda fn: captured.__setitem__(fn.__name__, fn) or fn
    members.register(bot)
    return bot, captured["on_member_join"]


async def test_member_join_context_appele_meme_si_accueillir_leve(monkeypatch):
    bot, on_member_join = _bot_discord()
    monkeypatch.setattr(members.bienvenue, "accueillir", AsyncMock(side_effect=RuntimeError("boom")))
    appels = []

    async def _context(bot_, member_):
        appels.append(member_)

    monkeypatch.setattr("bot.discord.handlers._member_join_context", _context)
    membre = SimpleNamespace(id=1, name="alice")

    await on_member_join(membre)  # ne doit pas lever

    assert appels == [membre]


async def test_member_join_context_appele_quand_accueillir_reussit(monkeypatch):
    bot, on_member_join = _bot_discord()
    accueil = AsyncMock()
    monkeypatch.setattr(members.bienvenue, "accueillir", accueil)
    appels = []

    async def _context(bot_, member_):
        appels.append(member_)

    monkeypatch.setattr("bot.discord.handlers._member_join_context", _context)
    membre = SimpleNamespace(id=1, name="alice")

    await on_member_join(membre)

    accueil.assert_awaited_once_with(bot, membre)
    assert appels == [membre]
