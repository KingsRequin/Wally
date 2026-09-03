"""Le routage des réactions Discord : humeur et perception, rien d'autre.

Ce fichier gardait autrefois le court-circuit du sondage : un vote arrivait
comme une réaction et devait s'arrêter là, sinon trente votants faisaient un pic
de joie et trente lignes de perception. Le sondage vote désormais par BOUTONS,
donc le court-circuit n'a plus lieu d'être — et le chemin ordinaire, lui, doit
toujours passer.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.events.reactions import register
from tests.test_sondage_service import FauxBot, FauxSalon


class FauxBotEvents(FauxBot):
    def __init__(self, salon: FauxSalon) -> None:
        super().__init__(salon)
        self.reaction_tracker = MagicMock()
        self.config = SimpleNamespace(
            discord=SimpleNamespace(ignored_guilds={13}))
        self.handlers: dict = {}

    def event(self, fonction):
        self.handlers[fonction.__name__] = fonction
        return fonction


class _Emoji:
    def __init__(self, valeur: str) -> None:
        self.valeur = valeur

    def __str__(self) -> str:
        return self.valeur


@pytest.fixture
def monde(monkeypatch):
    salon = FauxSalon()
    bot = FauxBotEvents(salon)
    register(bot)
    perception = AsyncMock()
    monkeypatch.setattr("bot.discord.handlers._reactions_context", perception)
    return SimpleNamespace(bot=bot, salon=salon, perception=perception)


def _payload(monde, emoji: str, user_id: int = 7, guild_id: int = 1):
    return SimpleNamespace(message_id=monde.salon.message.id, guild_id=guild_id,
                           channel_id=monde.salon.id, user_id=user_id,
                           emoji=_Emoji(emoji),
                           member=SimpleNamespace(id=user_id, bot=False))


async def test_une_reaction_suit_son_chemin_habituel(monde):
    await monde.bot.handlers["on_raw_reaction_add"](_payload(monde, "😂"))
    monde.bot.reaction_tracker.record_discord_reaction.assert_called_once()
    monde.perception.assert_awaited_once()


async def test_la_reaction_de_wally_ne_compte_pas(monde):
    """Sans ça, chaque emoji qu'il pose lui-même lui remonterait le moral."""
    await monde.bot.handlers["on_raw_reaction_add"](_payload(monde, "😂", user_id=99))
    monde.bot.reaction_tracker.record_discord_reaction.assert_not_called()
    monde.perception.assert_not_awaited()


async def test_un_serveur_ignore_ne_remonte_rien(monde):
    await monde.bot.handlers["on_raw_reaction_add"](
        _payload(monde, "😂", guild_id=13))
    monde.bot.reaction_tracker.record_discord_reaction.assert_not_called()
    monde.perception.assert_not_awaited()


async def test_le_retrait_d_une_reaction_n_est_plus_ecoute(monde):
    """Son SEUL consommateur était le vote de sondage, passé aux boutons : un
    handler vide qui reste enregistré coûte un appel par décochage du serveur."""
    assert "on_raw_reaction_remove" not in monde.bot.handlers
