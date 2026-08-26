# tests/test_user_modeler.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.intelligence.memory.user_modeler import UserModeler


def _make(users, active_by_user):
    db = MagicMock()
    db.get_users_with_recent_facts = AsyncMock(return_value=users)
    db.get_active_facts_for_user = AsyncMock(side_effect=lambda uid, **k: active_by_user.get(uid, []))
    db.get_superseded_facts_for_user = AsyncMock(return_value=[{"content": "détestait le solo", "category": "PREF"}])
    db.get_gender_facts_for_user = AsyncMock(return_value=[])
    db.get_trust_score = AsyncMock(return_value=0.5)
    db.get_love_score = AsyncMock(return_value=0.2)
    db.upsert_user_profile = AsyncMock()
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value={"portrait": "portrait test"})
    return UserModeler(db, llm), db, llm


@pytest.mark.asyncio
async def test_no_users_is_noop():
    c, db, llm = _make([], {})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()
    llm.complete_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_without_active_facts_skipped():
    c, db, llm = _make(["discord:1"], {"discord:1": []})
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    db.upsert_user_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_portrait_generated_with_dialectic_material():
    active = {"discord:1": [{"content": "aime la stratégie", "category": "PREF"}]}
    c, db, llm = _make(["discord:1"], active)
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    # trust/love appelés avec l'id BRUT (sans préfixe)
    db.get_trust_score.assert_awaited_with("discord", "1")
    # la matière dialectique (faits révolus) est passée au LLM
    payload = llm.complete_structured.await_args.args[1][0]["content"]
    assert "aime la stratégie" in payload
    assert "détestait le solo" in payload
    db.upsert_user_profile.assert_awaited_once_with("discord:1", "portrait test")


@pytest.mark.asyncio
async def test_users_isolated_on_error():
    active = {"discord:1": [{"content": "f1", "category": "FAIT"}],
              "discord:2": [{"content": "f2", "category": "FAIT"}]}
    c, db, llm = _make(["discord:1", "discord:2"], active)
    async def boom(prompt, messages, schema, **k):
        if "f1" in messages[0]["content"]:
            raise RuntimeError("LLM down for user 1")
        return {"portrait": "ok"}
    llm.complete_structured.side_effect = boom
    await c.refresh_profiles(since="2026-06-28T00:00:00")
    upserted = [call.args[0] for call in db.upsert_user_profile.await_args_list]
    assert "discord:2" in upserted and "discord:1" not in upserted


# ── une identité NON RÉSOLUE n'est pas une personne ────────────────────
#
# `unknown:<pseudo>` est la clé provisoire sous laquelle `fact_extractor`
# range ce qu'il apprend d'un tiers qu'il ne sait pas encore rattacher à un
# compte. Elle est faite pour DISPARAÎTRE — `_reconcile_orphan_facts` déplace
# ses faits vers l'uid canonique dès que l'alias est résolu.
#
# `get_user_profile()` n'est appelé qu'avec l'uid canonique (`discord:…`,
# `twitch:…`) : un portrait rangé sous `unknown:` n'est donc lu par PERSONNE.
# Exactement le raisonnement déjà tenu pour `wally:` — et le 2026-08-26 la base
# en portait cinq, régénérés chaque nuit, un appel LLM chacun.
@pytest.mark.asyncio
async def test_une_identite_non_resolue_n_a_pas_de_portrait():
    faits = [{"content": "joue Apex", "category": "PREF"}]
    c, db, llm = _make(
        ["unknown:azra", "unknown:lilith", "discord:42"],
        {"unknown:azra": faits, "unknown:lilith": faits, "discord:42": faits},
    )

    await c.refresh_profiles(since="2026-08-01T00:00:00")

    portraits = [appel.args[0] for appel in db.upsert_user_profile.await_args_list]
    assert portraits == ["discord:42"], (
        f"un portrait a été écrit sous une identité non résolue : {portraits}"
    )
    assert llm.complete_structured.await_count == 1, (
        "un appel LLM a été dépensé pour une fiche que personne ne lira"
    )


@pytest.mark.asyncio
async def test_le_portrait_orphelin_part_avec_les_faits_rattaches():
    """Rattacher une identité doit emporter son portrait provisoire.

    `reassign_user` déplaçait les faits ; le portrait restait sous
    `unknown:<pseudo>`, orphelin. Il est bâti SUR ces faits — il ne décrit donc
    plus rien dès qu'ils changent de clé —, il n'est lu par personne, et il
    était régénéré chaque nuit à un appel LLM pièce.
    """
    from unittest.mock import AsyncMock, MagicMock

    from bot.intelligence.fact_extractor import FactExtractor

    store = MagicMock()
    store.reassign_user = AsyncMock(return_value=3)
    memoire = MagicMock()
    memoire.fact_store = store
    db = MagicMock()
    db.delete_user_profile = AsyncMock(return_value=True)

    fe = FactExtractor.__new__(FactExtractor)
    fe._memory = memoire
    fe._db = db

    await fe._reconcile_orphan_facts("azra", "discord:610")

    store.reassign_user.assert_awaited_once_with("unknown:azra", "discord:610")
    db.delete_user_profile.assert_awaited_once_with("unknown:azra")


@pytest.mark.asyncio
async def test_le_portrait_part_meme_si_aucun_fait_n_a_bouge():
    """Zéro fait déplacé ne veut pas dire zéro portrait à effacer.

    L'ancien code sortait sur `if not moved: return` — un portrait resté seul,
    sans fait derrière lui, ne partait donc jamais. C'est exactement le cas de
    `unknown:azra` et `unknown:azrael` en base.
    """
    from unittest.mock import AsyncMock, MagicMock

    from bot.intelligence.fact_extractor import FactExtractor

    store = MagicMock()
    store.reassign_user = AsyncMock(return_value=0)
    memoire = MagicMock()
    memoire.fact_store = store
    db = MagicMock()
    db.delete_user_profile = AsyncMock(return_value=True)

    fe = FactExtractor.__new__(FactExtractor)
    fe._memory = memoire
    fe._db = db

    await fe._reconcile_orphan_facts("azrael", "discord:419")

    db.delete_user_profile.assert_awaited_once_with("unknown:azrael")
