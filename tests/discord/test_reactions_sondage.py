"""Un vote de sondage s'arrête au sondage : ni humeur, ni perception."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.sondage import EMOJIS_VOTE
from bot.discord.events.reactions import register
from bot.discord.sondage_service import SondageService
from tests.test_sondage_service import FauxBot, FauxSalon


class FauxBotEvents(FauxBot):
    def __init__(self, salon: FauxSalon) -> None:
        super().__init__(salon)
        self.reaction_tracker = MagicMock()
        self.config = SimpleNamespace(
            discord=SimpleNamespace(ignored_guilds=set()))
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
    bot.sondages = SondageService(bot)
    monkeypatch.setattr(bot.sondages, "DELAI_MAJ_S", 0.01)
    register(bot)
    perception = AsyncMock()
    monkeypatch.setattr("bot.discord.handlers._reactions_context", perception)
    return SimpleNamespace(bot=bot, salon=salon, perception=perception)


def _payload(monde, emoji: str, user_id: int = 7):
    return SimpleNamespace(message_id=monde.salon.message.id, guild_id=1,
                           channel_id=monde.salon.id, user_id=user_id,
                           emoji=_Emoji(emoji),
                           member=SimpleNamespace(id=user_id, bot=False))


async def test_un_vote_ne_touche_ni_l_humeur_ni_la_perception(monde):
    await monde.bot.sondages.creer(salon=monde.salon, question="Quel jeu ?",
                                   options=["Apex", "RL"], auteur="Azraël")
    await monde.bot.handlers["on_raw_reaction_add"](_payload(monde, EMOJIS_VOTE[0]))
    monde.bot.reaction_tracker.record_discord_reaction.assert_not_called()
    monde.perception.assert_not_awaited()


async def test_une_reaction_ordinaire_suit_son_chemin_habituel(monde):
    """Le pendant du test précédent : sans lui, on couperait TOUTES les
    réactions du serveur en croyant ne couper que les votes."""
    await monde.bot.handlers["on_raw_reaction_add"](_payload(monde, "😂"))
    monde.bot.reaction_tracker.record_discord_reaction.assert_called_once()
    monde.perception.assert_awaited_once()


async def test_le_retrait_d_un_chiffre_retire_le_vote(monde):
    sondage = await monde.bot.sondages.creer(
        salon=monde.salon, question="Quel jeu ?", options=["Apex", "RL"])
    assert sondage is not None
    await monde.bot.handlers["on_raw_reaction_add"](_payload(monde, EMOJIS_VOTE[0]))
    await monde.bot.handlers["on_raw_reaction_remove"](_payload(monde, EMOJIS_VOTE[0]))
    assert sondage.depouiller().total == 0
