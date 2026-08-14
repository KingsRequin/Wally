# tests/test_twitch_eventsub_assign.py
"""Placement des souscriptions EventSub sur les WebSockets.

Une WebSocket EventSub n'accepte qu'UN utilisateur authentifié. Wally souscrit
avec deux jetons (bot et streamer), donc le placement traverse forcément un
refus 400 « subscriptions created by different users ». Ce qui se passe APRÈS ce
refus décide de la survie du chat Twitch : `Websocket.connect()` rejoue tout son
`_subscription_pool` à chaque reconnexion, et `_subscribe()` repose sur l'état
de `sub.created` pour savoir s'il doit publier un résultat.

Vécu en prod le 2026-08-14, en plein live : une coupure réseau ferme la
WebSocket, la reconnexion automatique lève `InvalidStateError` dans `pump()`,
la tâche meurt, et Wally devient SOURD sur Twitch jusqu'au chien de garde
(jusqu'à deux minutes). Les messages du chat n'arrivent que par EventSub.
"""
import asyncio
from types import SimpleNamespace

import pytest


def _sub(token="streamer_token"):
    """Une vraie souscription twitchio : `created` est une Future pendante."""
    from twitchio.ext.eventsub.websocket import _Subscription
    from twitchio.ext.eventsub import models

    return _Subscription(("channel.subscribe", 1, models.ChannelSubscribeData),
                         {"broadcaster_user_id": "42"}, token)


class FakeSocket:
    """Socket minimal : un pool réel, et une réponse programmée par Twitch."""

    def __init__(self, *, status=None, slots=10):
        from twitchio.ext.eventsub.websocket import _WakeupList

        self._subscription_pool = _WakeupList()
        self.remaining_slots = slots
        # `None` = Twitch accepte ; un entier = le statut du refus.
        self._status = status
        self.connected = False

    async def connect(self, reconnect_url=None):
        self.connected = True

    def add_subscription(self, sub) -> None:
        # Le vrai `add_subscription` empile puis laisse `_wakeup_and_connect`
        # résoudre la Future depuis une autre tâche : on reproduit ce délai,
        # sans quoi le test ne verrait jamais l'ordre réel des opérations.
        self._subscription_pool.append(sub)
        asyncio.get_running_loop().call_soon(self._resolve, sub)

    def _resolve(self, sub) -> None:
        if sub.created is None or sub.created.done():
            return
        if self._status is None:
            sub.created.set_result((True, None))
        else:
            sub.created.set_result((False, self._status))


async def _assign(sockets, sub, new_socket=None):
    """Joue `_assign_subscription` corrigé sur un client factice."""
    from bot.twitch.events import _patch_socket_tracking
    from twitchio.ext.eventsub import EventSubWSClient

    _patch_socket_tracking()
    client = SimpleNamespace(_sockets=list(sockets), client=None, _http=None)
    if new_socket is None:
        await EventSubWSClient._assign_subscription(client, sub)
    else:
        import twitchio.ext.eventsub.websocket as ws_mod

        original = ws_mod.Websocket
        ws_mod.Websocket = lambda *a, **k: new_socket
        try:
            await EventSubWSClient._assign_subscription(client, sub)
        finally:
            ws_mod.Websocket = original
    return client


@pytest.mark.asyncio
async def test_socket_refusant_en_400_ne_garde_pas_la_souscription():
    """Un 400 « different users » doit VIDER la souscription du socket fautif.

    Sans ça, le socket du bot conserve les six souscriptions du streamer qu'il
    vient de refuser. Elles sont rejouées à chaque reconnexion, échouent, et
    polluent la remontée — quand elles ne la tuent pas.
    """
    refuse = FakeSocket(status=400)
    accepte = FakeSocket(status=None)
    sub = _sub()

    await _assign([refuse, accepte], sub)

    assert sub not in refuse._subscription_pool, (
        "la souscription refusée reste dans le pool du socket du bot : "
        "elle sera rejouée à chaque reconnexion"
    )
    assert sub in accepte._subscription_pool


@pytest.mark.asyncio
async def test_souscription_placee_sur_un_socket_neuf_ne_laisse_pas_de_future_resolue():
    """`sub.created` doit retomber à None, y compris via le socket de secours.

    C'est LE défaut qui rendait Wally sourd : la branche « aucune place libre »
    posait la souscription et repartait sans attendre. `_wakeup_and_connect`
    résolvait la Future dans son coin, et plus personne ne la remettait à None.
    À la reconnexion suivante, `_subscribe()` voyait une Future encore présente
    et appelait `set_result` dessus une deuxième fois — `InvalidStateError`,
    remontée jusqu'à `pump()`, tâche morte, chat Twitch coupé.
    """
    plein = FakeSocket(status=400, slots=0)
    neuf = FakeSocket(status=None)
    sub = _sub()

    await _assign([plein], sub, new_socket=neuf)

    assert sub in neuf._subscription_pool
    assert sub.created is None, (
        "future laissée résolue : la prochaine reconnexion lèvera "
        "InvalidStateError et tuera la WebSocket"
    )


@pytest.mark.asyncio
async def test_socket_de_secours_est_memorise():
    """La correction d'origine (fuite de sockets) ne doit pas régresser."""
    plein = FakeSocket(status=400, slots=0)
    neuf = FakeSocket(status=None)

    client = await _assign([plein], _sub(), new_socket=neuf)

    assert neuf in client._sockets
    assert neuf.connected
