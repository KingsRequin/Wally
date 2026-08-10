# tests/test_gate_uid_prefixe.py
"""Le ResponseGate doit lire ET écrire sous `platform:raw_id`.

Convention `CLAUDE.md` : le fact store est indexé sur la forme préfixée.
Avec l'id nu, le gate lisait 0 fait de relation (269 en base, tous préfixés)
et écrivait ses traces d'ignorance dans un espace que personne ne lit
(73 faits orphelins constatés en prod le 2026-08-10).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import bot.discord.handlers as h


class _Store:
    def __init__(self):
        self.lus: list[str] = []
        self.ecrits: list[str] = []

    async def get_by_user(self, user_id, categories=None):
        self.lus.append(user_id)
        return []

    async def add(self, fact):
        self.ecrits.append(fact.user_id)


@pytest.mark.asyncio
async def test_le_gate_lit_les_relations_sous_la_forme_prefixee():
    store = _Store()
    gate = MagicMock()
    gate._fact_store = store
    gate.decide = AsyncMock(return_value=MagicMock(decision="RESPOND", reason=None, emoji=None))

    bot = MagicMock()
    bot.response_gate = gate
    bot.memory._user_id = lambda p, u: f"{p}:{u}"

    uid = await h._canonical_uid(bot, "discord", "610550333042589752")
    await store.get_by_user(uid)

    assert store.lus == ["discord:610550333042589752"]


@pytest.mark.asyncio
async def test_l_alias_canonique_est_respecte():
    """`_user_id()` résout aussi les alias : le gate doit passer par lui, pas concaténer."""
    bot = MagicMock()
    bot.memory._user_id = lambda p, u: "discord:CANONIQUE"
    assert await h._canonical_uid(bot, "discord", "999") == "discord:CANONIQUE"


@pytest.mark.asyncio
async def test_repli_si_la_memoire_est_absente():
    bot = MagicMock()
    bot.memory = None
    assert await h._canonical_uid(bot, "discord", "42") == "discord:42"


@pytest.mark.asyncio
async def test_un_compte_twitch_lie_retrouve_le_portrait_de_son_compte_discord():
    """Le portrait est écrit sous l'uid canonique ; le lire sous `twitch:raw`
    le rendait introuvable pour les 24 comptes liés."""
    bot = MagicMock()
    bot.memory._user_id = lambda p, u: (
        "discord:182881216884637696" if (p, u) == ("twitch", "90774597") else f"{p}:{u}"
    )
    uid = await h._canonical_uid(bot, "twitch", "90774597")
    assert uid == "discord:182881216884637696"


@pytest.mark.asyncio
async def test_la_trace_d_ignorance_est_ecrite_sous_l_uid_prefixe():
    from bot.intelligence.gate import ResponseGate

    store = _Store()
    llm = MagicMock()
    llm.complete_structured = AsyncMock(
        return_value={"decision": "IGNORE", "reason": "hors sujet"}
    )
    g = ResponseGate(llm, store)
    with patch("bot.intelligence.gate.bot_name", return_value="Wally"):
        await g.decide(
            message_content="salut",
            author_user_id="discord:610550333042589752",
            emotion_state={"joy": 0.1},
            relationship_facts=[],
            active_desires=[],
        )
    assert store.ecrits == ["discord:610550333042589752"]
