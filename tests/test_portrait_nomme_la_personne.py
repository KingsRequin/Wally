# tests/test_portrait_nomme_la_personne.py
"""Le portrait doit dire DE QUI il parle.

Sans le nom dans le payload, le seul nom du contexte est celui du bot
({{BOT_NAME}} dans le prompt système) : le LLM attribue alors le portrait à
Wally lui-même. Constaté en prod le 2026-08-10 sur 11 fiches / 95.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.memory.user_modeler import UserModeler


def _make(username="wengers14"):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=["discord:440632152091000844"])
    db.get_active_facts_for_user = AsyncMock(return_value=[{"content": "habite dans le Sud", "category": "FAIT"}])
    db.get_superseded_facts_for_user = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    db.get_memory_username = AsyncMock(return_value=username)
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), db, llm


def _payload(llm):
    return llm.complete_structured.await_args.args[1][0]["content"]


@pytest.mark.asyncio
async def test_le_nom_de_la_personne_est_dans_le_payload():
    c, db, llm = _make()
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    assert "wengers14" in _payload(llm)


@pytest.mark.asyncio
async def test_le_nom_ouvre_le_payload_avant_les_traits():
    """Le nom doit précéder les faits : sinon il se lit comme un fait parmi d'autres."""
    c, db, llm = _make()
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    p = _payload(llm)
    assert p.index("wengers14") < p.index("habite dans le Sud")


@pytest.mark.asyncio
async def test_sans_username_on_retombe_sur_l_id_brut():
    """Un nom absent ne doit pas rendre le portrait anonyme — donc attribuable au bot."""
    c, db, llm = _make(username=None)
    await c.refresh_profiles(since="2026-08-09T00:00:00")
    assert "440632152091000844" in _payload(llm)


@pytest.mark.asyncio
async def test_le_prompt_systeme_reclame_le_nom():
    """La consigne doit nommer la personne, sinon le modèle n'a pas de raison de s'en servir."""
    from bot.intelligence.memory.user_modeler import _PORTRAIT_PROMPT
    bas = _PORTRAIT_PROMPT.lower()
    assert "pseudo" in bas
    # La consigne doit exclure explicitement le bot comme sujet du portrait.
    assert "jamais de" in bas
