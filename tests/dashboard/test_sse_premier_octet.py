"""Un flux SSE sans événement doit quand même ouvrir la connexion tout de suite.

`GZipMiddleware` retient les en-têtes jusqu'au premier corps : un flux qui
n'émet rien avant son keepalive laisse le client sans `onopen` pendant 15 s,
et le panneau affiche « déconnecté » alors que tout va bien.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from bot.discord.voice.feed import VoiceFeed
from bot.intelligence.cognitive_feed import CognitiveFeed


def _requete(**etat):
    wally = types.SimpleNamespace(**etat)
    requete = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally)))

    async def _connecte():
        return False

    requete.is_disconnected = _connecte
    return requete


@pytest.mark.parametrize("route, attribut, flux", [
    ("bot.dashboard.routes.voice:voice_sse", "voice_feed", VoiceFeed),
    ("bot.dashboard.routes.cognitive:cognitive_sse", "cognitive_feed", CognitiveFeed),
])
async def test_le_premier_octet_part_sans_attendre(route, attribut, flux):
    import importlib

    module, nom = route.split(":")
    fonction = getattr(importlib.import_module(module), nom)
    feed = flux()
    reponse = await fonction(_requete(**{attribut: feed}))
    gen = reponse.body_iterator
    premier = await asyncio.wait_for(gen.__anext__(), timeout=1)
    assert premier.startswith(":")
    await gen.aclose()
