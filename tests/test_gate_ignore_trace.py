"""Trace des décisions d'ignorer : utile à court terme, pas en mémoire longue.

Constat en prod : 81 faits « Wally a choisi d'ignorer ce message » actifs, dont
10 sans le moindre motif, et aucun avec péremption — ils s'accumulaient dans la
mémoire long terme et pouvaient être repêchés lors d'un rappel.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.intelligence.gate import _IGNORE_TRACE_TTL_HOURS, ResponseGate


def _gate(decision: dict):
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value=decision)
    store = MagicMock()
    store.add = AsyncMock()
    return ResponseGate(llm, fact_store=store), store


@pytest.mark.asyncio
async def test_une_ignorance_motivee_est_tracee_avec_peremption():
    gate, store = _gate({"decision": "IGNORE", "reason": "message intrusif"})
    await gate.decide("salut", "discord:1", {}, [], [])

    store.add.assert_awaited_once()
    fact = store.add.await_args.args[0]
    assert "message intrusif" in fact.content
    assert fact.expires_at is not None  # ne doit pas rester en mémoire longue


@pytest.mark.asyncio
async def test_une_ignorance_sans_motif_n_est_pas_memorisee():
    """« aucune raison spécifiée » n'apprend rien sur personne."""
    gate, store = _gate({"decision": "IGNORE", "reason": None})
    await gate.decide("salut", "discord:1", {}, [], [])
    store.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_reponse_normale_n_ecrit_rien():
    gate, store = _gate({"decision": "RESPOND"})
    await gate.decide("salut", "discord:1", {}, [], [])
    store.add.assert_not_awaited()


def test_la_peremption_reste_courte():
    assert 0 < _IGNORE_TRACE_TTL_HOURS <= 72
