"""Deux redémarrages EventSub concurrents ne doivent laisser qu'un seul client.

Vécu le 2026-08-08 sur la chaîne d'Azraël : Wally répondait deux fois au même
message. Twitch confirmait deux souscriptions `channel.chat.message` actives sur
deux sessions WebSocket distinctes.

`_restart_eventsub()` remet `_eventsub_client` à None AVANT de reconstruire, et
la reconstruction dure une quinzaine de secondes (souscriptions séquentielles
espacées de 1.5 s). Un second appel dans cette fenêtre lisait donc None, ne
fermait rien, et repartait pour une seconde série : le client de la première
série restait vivant, orphelin mais sa WebSocket toujours ouverte — chaque
message du chat arrivait deux fois, jusqu'au redémarrage du process.
"""
import asyncio

import pytest

from bot.twitch.bot import WallyTwitch


class _FakeSock:
    def __init__(self):
        self.closed = False
        self._sock = self
        self._pump_task = None

    async def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self, name):
        self.name = name
        self._sockets = [_FakeSock()]


def _bot():
    """Instance nue : `start()` n'est jamais appelé, seul le restart est testé."""
    bot = WallyTwitch.__new__(WallyTwitch)
    bot._eventsub_client = _FakeClient("initial")
    WallyTwitch._init_eventsub_restart_state(bot)
    return bot


@pytest.mark.asyncio
async def test_restarts_concurrents_ne_laissent_quun_client(monkeypatch):
    created = []

    async def _fake_start(bot):
        # Reconstruction lente : c'est cette fenêtre qui laissait passer le second
        # appel dans la version buguée.
        client = _FakeClient(f"client-{len(created)}")
        created.append(client)
        await asyncio.sleep(0.05)
        bot._eventsub_client = client

    monkeypatch.setattr("bot.twitch.events.start_eventsub_client", _fake_start)

    bot = _bot()
    first = bot._eventsub_client

    await asyncio.gather(bot._restart_eventsub(), bot._restart_eventsub())

    # Le client d'origine et tout client intermédiaire sont fermés : seul le
    # dernier reste vivant. Sinon Twitch livre chaque message en double.
    alive = [c for c in [first, *created] if c is not bot._eventsub_client
             and not all(s.closed for s in c._sockets)]
    assert alive == [], f"clients orphelins encore ouverts : {[c.name for c in alive]}"
    assert bot._eventsub_client is created[-1]


@pytest.mark.asyncio
async def test_une_rafale_de_demandes_ne_declenche_quun_restart_en_attente(monkeypatch):
    """Le quota de CRÉATION Twitch se recharge en minutes : empiler N restarts
    identiques les ferait tomber en 429. Un seul suffit à refléter l'état final."""
    created = []

    async def _fake_start(bot):
        client = _FakeClient(f"client-{len(created)}")
        created.append(client)
        await asyncio.sleep(0.05)
        bot._eventsub_client = client

    monkeypatch.setattr("bot.twitch.events.start_eventsub_client", _fake_start)

    bot = _bot()
    await asyncio.gather(*(bot._restart_eventsub() for _ in range(6)))

    # 1 restart en cours + 1 en attente = 2 reconstructions, pas 6.
    assert len(created) == 2


@pytest.mark.asyncio
async def test_un_restart_seul_ferme_le_client_precedent(monkeypatch):
    async def _fake_start(bot):
        bot._eventsub_client = _FakeClient("nouveau")

    monkeypatch.setattr("bot.twitch.events.start_eventsub_client", _fake_start)

    bot = _bot()
    ancien = bot._eventsub_client
    await bot._restart_eventsub()

    assert all(s.closed for s in ancien._sockets)
    assert bot._eventsub_client is not ancien
