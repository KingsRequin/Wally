"""Tests Phase 3 — dédup sémantique des désirs à l'écriture + drop_desire/doubt_memory."""
import pytest
import pytest_asyncio

from bot.intelligence.action_dispatcher import ActionDispatcher, _same_desire
from bot.intelligence.meta_agent import MetaDecision
from bot.intelligence.memory.facts import (
    AtomicFact, FactCategory, FactStatus, SQLiteFactStore,
)


@pytest_asyncio.fixture
async def store(tmp_path):
    from bot.db.schema_v2 import create_v2_tables
    db_path = str(tmp_path / "p3.db")
    await create_v2_tables(db_path)
    return SQLiteFactStore(db_path)


async def _add_desire(store, content, conf=0.8):
    return await store.add(AtomicFact(
        user_id="wally:self", content=content,
        category=FactCategory.DESIRE, confidence=conf,
    ))


# --- _same_desire ---------------------------------------------------------- #

def test_same_desire_matches_paraphrase():
    assert _same_desire(
        "Demander à KingsRequin quels animés il regarde en ce moment",
        "Demander à KingsRequin ce qu'il regarde comme animés en ce moment",
    )


def test_same_desire_rejects_unrelated():
    assert not _same_desire(
        "Demander à KingsRequin ses animés",
        "Creuser l'origine du souvenir jubeii1979 Apex Legends",
    )


# --- create_desire dedup --------------------------------------------------- #

@pytest.mark.asyncio
async def test_create_desire_merges_duplicate(store):
    await _add_desire(store, "Demander à KingsRequin quels animés il regarde en ce moment")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="create_desire",
        act_args={"content": "Demander à KingsRequin ce qu'il regarde comme animés en ce moment"},
    ))
    # get_by_user fait SELECT * (support_count inclus, contrairement à
    # search_by_category qui ne le sélectionne pas).
    actives = await store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
    assert len(actives) == 1                 # pas de doublon créé
    assert actives[0].support_count == 2     # l'existant a été confirmé


@pytest.mark.asyncio
async def test_create_desire_distinct_is_added(store):
    await _add_desire(store, "Demander à KingsRequin ses animés")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="create_desire",
        act_args={"content": "Creuser l'origine du souvenir jubeii1979 Apex"},
    ))
    actives = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25)
    assert len(actives) == 2


# --- drop_desire ----------------------------------------------------------- #

@pytest.mark.asyncio
async def test_drop_desire_by_id(store):
    did = await _add_desire(store, "vieux désir caduc")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="drop_desire", act_args={"desire_id": did}))
    actives = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25)
    assert actives == []


@pytest.mark.asyncio
async def test_drop_desire_by_description(store):
    await _add_desire(store, "Vérifier si mks_zedd s'est déjà dit fou en chat")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="drop_desire",
        act_args={"description": "vérifier auprès de KingsRequin si mks_zedd s'est dit fou"}))
    actives = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25)
    assert actives == []


# --- note_to_self dedup (reminder/question → DESIRE) ----------------------- #

@pytest.mark.asyncio
async def test_note_to_self_reminder_merges_duplicate(store):
    """Un reminder qui paraphrase un désir actif est fusionné, pas empilé
    (même contrat que create_desire : le chemin note_to_self atterrit aussi
    dans les DESIRE)."""
    await _add_desire(store, "Ce soir quand le serveur est actif : lancer le sujet mks_zedd qui apprend le russe")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "Ce soir si le serveur s'anime : lancer le sujet mks_zedd et le russe", "kind": "reminder"},
    ))
    actives = await store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
    assert len(actives) == 1                 # pas de doublon créé
    assert actives[0].support_count == 2     # l'existant a été confirmé


@pytest.mark.asyncio
async def test_note_to_self_question_merges_duplicate(store):
    """kind=question mappe aussi sur DESIRE → même dédup."""
    await _add_desire(store, "Demander à KingsRequin quels animés il regarde en ce moment")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "Demander à KingsRequin ce qu'il regarde comme animés en ce moment", "kind": "question"},
    ))
    actives = await store.get_by_user("wally:self", categories=[FactCategory.DESIRE])
    assert len(actives) == 1


@pytest.mark.asyncio
async def test_note_to_self_distinct_reminder_is_added(store):
    await _add_desire(store, "Demander à KingsRequin ses animés")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "Creuser l'origine du souvenir jubeii1979 Apex", "kind": "reminder"},
    ))
    actives = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25)
    assert len(actives) == 2


@pytest.mark.asyncio
async def test_note_to_self_scheduled_reminder_not_deduped(store):
    """Un rappel à échéance précise (in_minutes) est une intention datée :
    on ne le fusionne PAS, même s'il paraphrase un désir existant."""
    await _add_desire(store, "lancer le sujet mks_zedd qui apprend le russe ce soir")
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="note_to_self",
        act_args={"note": "lancer le sujet mks_zedd et le russe", "kind": "reminder", "in_minutes": 60},
    ))
    actives = await store.search_by_category(FactCategory.DESIRE, status=FactStatus.ACTIVE, limit=25)
    assert len(actives) == 2


# --- doubt_memory ---------------------------------------------------------- #

@pytest.mark.asyncio
async def test_doubt_memory_by_id(store):
    fid = await store.add(AtomicFact(
        user_id="discord:174", content="jubeii1979 plays Apex Legends",
        category=FactCategory.FAIT, confidence=0.7,
        subject="jubeii1979", predicate="plays", object_="Apex Legends",
    ))
    disp = ActionDispatcher(fact_store=store)
    await disp.dispatch(MetaDecision(
        action="ACT", act_name="doubt_memory", act_args={"fact_id": fid}))
    rows = await store.get_by_ids([fid], min_confidence=0.0)
    # marqué needs_review → plus actif ; confiance divisée par 2
    assert rows == [] or rows[0].status != FactStatus.ACTIVE
    # vérifie via accès direct au statut
    import aiosqlite
    async with aiosqlite.connect(store._db_path) as db:
        cur = await db.execute("SELECT status, confidence FROM atomic_facts WHERE id=?", (fid,))
        status, conf = await cur.fetchone()
    assert status == "needs_review"
    assert conf == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_store_doubt_method(store):
    fid = await _add_desire(store, "un souvenir douteux", conf=0.8)
    await store.doubt(fid)
    import aiosqlite
    async with aiosqlite.connect(store._db_path) as db:
        cur = await db.execute("SELECT status, confidence FROM atomic_facts WHERE id=?", (fid,))
        status, conf = await cur.fetchone()
    assert status == "needs_review"
    assert conf == pytest.approx(0.4)
