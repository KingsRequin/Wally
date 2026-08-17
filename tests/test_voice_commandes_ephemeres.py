"""`/join` et `/ecoute` répondent en privé, à la personne qui les a lancées.

Demande de l'owner : « la commande /ecoute devrait répondre avec un message
éphémère, de même pour la /join ».

Les deux commandes servent à mettre Wally en place, souvent en plein live et
souvent plusieurs fois de suite (un redémarrage, un salon changé). Chaque appel
laissait deux traces publiques dans le salon : le « réfléchit… » du `defer`,
puis la confirmation. C'est du bruit dans un salon qu'on regarde pendant un
stream, pour une manœuvre qui ne concerne que celui qui la fait.

⚠️ Les DEUX comptent. Déférer sans `ephemeral=True` rend le « réfléchit… »
public quoi qu'on fasse ensuite : le `followup` éphémère arrive après, et
l'attente reste affichée à tout le monde. C'est le piège de cette correction —
on croit avoir masqué la réponse alors qu'on n'a masqué que la moitié.

`/leave` reste PUBLIQUE, volontairement : un départ se voit de toute façon dans
le salon, et l'annoncer répond à la question « pourquoi il est parti ».
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.commands.voice_cmd import VoiceCog


def _interaction():
    it = MagicMock()
    it.response.defer = AsyncMock()
    it.response.send_message = AsyncMock()
    it.followup.send = AsyncMock()
    return it


def _cog(**service):
    bot = MagicMock()
    for cle, valeur in service.items():
        setattr(bot.voice_service, cle, valeur)
    cog = VoiceCog.__new__(VoiceCog)
    cog.bot = bot
    return cog, bot


@pytest.mark.asyncio
async def test_join_ne_laisse_aucune_trace_publique():
    cog, bot = _cog(join=AsyncMock())
    it = _interaction()
    it.user.voice.channel = MagicMock(name="Général")

    await VoiceCog.join.callback(cog, it)

    assert it.response.defer.await_args.kwargs.get("ephemeral") is True, (
        "sans ça, le « réfléchit… » reste affiché à tout le salon")
    assert it.followup.send.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_ecoute_ne_laisse_aucune_trace_publique():
    cog, bot = _cog(join=AsyncMock())
    bot.config.bot.stream_voice_channel_id = 123
    bot.get_channel.return_value = MagicMock(name="Stream")
    it = _interaction()

    await VoiceCog.ecoute.callback(cog, it, None)

    assert it.response.defer.await_args.kwargs.get("ephemeral") is True
    assert it.followup.send.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_le_depart_reste_annonce_a_tout_le_monde():
    """Un départ se voit dans le salon : le taire laisserait la question
    « pourquoi il est parti ? » sans réponse."""
    cog, bot = _cog(leave=AsyncMock(), is_connected=True)
    it = _interaction()

    await VoiceCog.leave.callback(cog, it)

    assert not it.response.defer.await_args.kwargs.get("ephemeral")
    assert not it.followup.send.await_args.kwargs.get("ephemeral")
