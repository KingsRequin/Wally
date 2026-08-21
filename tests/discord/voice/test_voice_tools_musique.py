"""« C'est quoi ce son ? » se pose autant à voix haute qu'à l'écrit.

Le §10 veut la LECTURE ouverte à tout le monde — dire ce qui passe n'est pas un
pouvoir. Elle manquait pourtant en vocal, comme elle manquait sur Discord : le
service n'était posé que sur l'adaptateur Twitch, et les gardes
`getattr(bot, "music", None)` se taisaient partout ailleurs.

Le PILOTAGE, lui, reste au chat Twitch : un salon vocal ne porte aucun badge de
modérateur. Le refus doit alors ORIENTER — quelqu'un qui demande la musique
suivante à voix haute n'a rien tenté de louche, il n'est pas au bon endroit.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.tools import build_voice_tools, make_voice_tool_executor


def _noms(outils):
    return {o["function"]["name"] for o in outils}


async def _outils(bot):
    bot.web_search.available = False
    bot.action_service = None
    return await build_voice_tools(bot)


@pytest.mark.asyncio
async def test_la_musique_est_proposee_en_vocal():
    bot = MagicMock()
    bot.music = MagicMock()
    assert "music_control" in _noms(await _outils(bot))


@pytest.mark.asyncio
async def test_sans_service_musique_l_outil_n_est_PAS_propose():
    """Un outil mort ferait promettre une réponse qui n'arriverait jamais."""
    bot = MagicMock()
    bot.music = None
    assert "music_control" not in _noms(await _outils(bot))


@pytest.mark.asyncio
async def test_dire_ce_qui_passe_repond_a_voix_haute():
    from bot.core.music import MusicService

    bot = MagicMock()
    bot.music = MusicService()
    bot.music.battement(actif=True, joue=True, titre="Numb",
                        artiste="Linkin Park",
                        url="https://youtube.com/watch?v=abc", accuses=[])
    executor = make_voice_tool_executor(bot, MagicMock(),
                                        current_speaker_id=lambda: "1")
    dit = await executor("music_control", json.dumps({"action": "now"}))
    assert "Numb" in dit and "Linkin Park" in dit


@pytest.mark.asyncio
async def test_piloter_depuis_le_VOCAL_oriente_au_lieu_de_refuser():
    from bot.core.music import MusicService

    bot = MagicMock()
    bot.music = MusicService()
    executor = make_voice_tool_executor(bot, MagicMock(),
                                        current_speaker_id=lambda: "1")
    dit = await executor("music_control", json.dumps({"action": "next"}))
    assert "Twitch" in dit
    # Et surtout : l'ordre ne part pas.
    assert bot.music.battement(actif=True, joue=True, titre="Numb", artiste="LP",
                               url="https://youtube.com/watch?v=abc") == []


@pytest.mark.asyncio
async def test_un_JSON_tordu_ne_fait_pas_tomber_l_appel():
    """Les arguments viennent d'un modèle de langage, pas d'un formulaire."""
    bot = MagicMock()
    bot.music = MagicMock()
    executor = make_voice_tool_executor(bot, MagicMock(),
                                        current_speaker_id=lambda: "1")
    dit = await executor("music_control", "{pas du json")
    assert isinstance(dit, str) and dit
