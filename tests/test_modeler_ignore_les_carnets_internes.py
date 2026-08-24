# tests/test_modeler_ignore_les_carnets_internes.py
"""`wally:self` et `wally:emotes` ne sont pas des personnes.

Ce sont les carnets internes du bot — ses pensées, son catalogue d'emotes —
rangés sous un faux identifiant. `get_user_profile()` n'est jamais appelé avec :
leur portrait n'est lu par personne et coûtait un appel LLM chaque nuit.

Le 2026-08-24, le modèle a rendu pour `wally:self` le portrait de
KassandreYunikon, dont les pensées de Wally parlaient beaucoup ce jour-là.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.memory.user_modeler import UserModeler


def _make(users):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=users)
    db.get_active_facts_for_user = AsyncMock(
        return_value=[{"content": "joue à Apex", "category": "FAIT"}]
    )
    db.get_superseded_facts_for_user = AsyncMock(return_value=[])
    db.get_gender_facts_for_user = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    db.get_memory_username = AsyncMock(return_value="quelqu_un")
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), db, llm


@pytest.mark.asyncio
async def test_les_carnets_internes_ne_sont_pas_modelises():
    c, db, llm = _make(["wally:self", "wally:emotes"])
    await c.refresh_profiles(since="2026-08-01T00:00:00")
    db.upsert_user_profile.assert_not_awaited()
    llm.complete_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_les_personnes_passent_toujours():
    c, db, llm = _make(["wally:self", "discord:610550333042589752"])
    await c.refresh_profiles(since="2026-08-01T00:00:00")
    modelises = [call.args[0] for call in db.upsert_user_profile.await_args_list]
    assert modelises == ["discord:610550333042589752"]
