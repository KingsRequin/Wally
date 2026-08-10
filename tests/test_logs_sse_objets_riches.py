"""Un log qui porte un objet Discord ne doit pas disparaître de l'onglet Logs.

Relevé le 2026-08-10 dans les logs de production, au démarrage :

    --- Logging error in Loguru Handler #4 ---
    TypeError: cannot pickle '_asyncio.Future' object
    --- End of logging error ---

Le sink SSE était installé avec `enqueue=True`, ce qui fait pickler le record
ENTIER par loguru — y compris `extra`, où atterrissent les kwargs de l'appelant.
`logger.info("Discord bot ready as {user}", user=self.user)` y met un
`ClientUser`, qui traîne un `_asyncio.Future`. Le pickle échouait et la ligne
n'atteignait jamais l'onglet Logs.

Ce n'est pas une ligne isolée : TOUTE ligne loguée avec un objet Discord en
argument disparaissait, sans que rien ne le signale côté dashboard. Or le sink
ne lit que trois champs — niveau, message, heure. Il n'a jamais eu besoin de
sérialiser quoi que ce soit.
"""
import asyncio

import pytest
from loguru import logger

from bot.dashboard.routes import sse


class _Impicklable:
    """Ce qu'est un `ClientUser` du point de vue du pickle."""

    def __init__(self):
        self.futur = asyncio.Future()

    def __str__(self):
        return "Wally#0058"


@pytest.fixture
def sink_propre():
    """Installe le sink et le retire, sans toucher aux autres handlers."""
    sse._sink_id = None
    sse._boucle = None
    sse.setup_log_sink()
    file = asyncio.Queue(maxsize=50)
    sse._log_queues.append(file)
    yield file
    sse._log_queues.remove(file)
    if sse._sink_id is not None:
        logger.remove(sse._sink_id)
    sse._sink_id = None


@pytest.mark.asyncio
async def test_un_log_portant_un_objet_non_picklable_arrive_quand_meme(sink_propre):
    logger.info("Discord bot ready as {user}", user=_Impicklable())

    await asyncio.sleep(0)
    assert not sink_propre.empty(), (
        "la ligne n'a pas atteint l'onglet Logs — c'est exactement ce que "
        "`enqueue=True` provoquait en production"
    )
    entree = sink_propre.get_nowait()
    assert entree["message"] == "Discord bot ready as Wally#0058"
    assert entree["level"] == "INFO"


@pytest.mark.asyncio
async def test_un_log_emis_depuis_un_thread_arrive_aussi(sink_propre):
    """`put_nowait` sur une `asyncio.Queue` n'est pas thread-safe.

    Des `logger.warning()` partent bel et bien depuis des `asyncio.to_thread`
    (analyse émotionnelle à chaque message, pipeline vocal, scrape). C'est la
    raison d'être du `enqueue=True` d'origine — elle reste valable, mais se
    règle par `call_soon_threadsafe`, sans pickler quoi que ce soit.
    """
    await asyncio.to_thread(logger.warning, "émis depuis un thread")

    await asyncio.sleep(0.05)   # laisse passer le call_soon_threadsafe
    messages = []
    while not sink_propre.empty():
        messages.append(sink_propre.get_nowait()["message"])
    assert "émis depuis un thread" in messages


@pytest.mark.asyncio
async def test_le_sink_reste_idempotent(sink_propre):
    """Deux appels ne doivent pas doubler chaque ligne dans l'onglet."""
    premier = sse._sink_id
    sse.setup_log_sink()
    assert sse._sink_id == premier

    logger.info("une seule fois")
    await asyncio.sleep(0)

    vus = []
    while not sink_propre.empty():
        vus.append(sink_propre.get_nowait()["message"])
    assert vus.count("une seule fois") == 1
