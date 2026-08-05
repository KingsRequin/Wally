"""Cycle de vie des buts.

Constat en prod : sur 111 buts créés, aucun n'était identifiable comme accompli
— `fulfill_goal` écrivait ARCHIVED, le même statut que l'abandon. Et un but
pouvait être avancé 21 fois sans jamais être clos.
"""
import aiosqlite
import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.memory.facts import (
    AtomicFact,
    FactCategory,
    FactStatus,
    SQLiteFactStore,
)


@pytest.fixture
async def store(tmp_path):
    path = str(tmp_path / "facts.db")
    await create_v2_tables(path)
    return SQLiteFactStore(path)


async def _goal(store) -> int:
    return await store.add(
        AtomicFact(
            user_id="wally:self",
            content="Tenir un but jusqu'au bout",
            category=FactCategory.GOAL,
        )
    )


async def _status(store, fact_id: int) -> str:
    async with aiosqlite.connect(store._db_path) as db:
        cur = await db.execute("SELECT status FROM atomic_facts WHERE id = ?", (fact_id,))
        return (await cur.fetchone())[0]


def test_fulfilled_est_distinct_d_archived():
    assert FactStatus.FULFILLED.value == "fulfilled"
    assert FactStatus.FULFILLED != FactStatus.ARCHIVED


@pytest.mark.asyncio
async def test_but_accompli_se_distingue_d_un_but_abandonne(store):
    accompli, abandonne = await _goal(store), await _goal(store)
    await store.set_status(accompli, FactStatus.FULFILLED)
    await store.set_status(abandonne, FactStatus.ARCHIVED)

    assert await _status(store, accompli) == "fulfilled"
    assert await _status(store, abandonne) == "archived"


@pytest.mark.asyncio
async def test_un_but_accompli_sort_du_contexte(store):
    """Il ne doit plus ré-amorcer la boucle cognitive une fois atteint."""
    gid = await _goal(store)
    await store.set_status(gid, FactStatus.FULFILLED)
    assert await store.get_by_ids([gid]) == []


@pytest.mark.asyncio
async def test_un_but_qui_stagne_finit_par_etre_clos(store):
    gid = await _goal(store)
    # Le quota d'étapes est consommé sans jamais aboutir
    for i in range(3):
        assert await store.append_progress(gid, f"étape {i}", max_step_lines=3) is True
    assert await _status(store, gid) == "active"

    # L'étape de trop clôt le but
    assert await store.append_progress(gid, "encore", max_step_lines=3) is True
    assert await _status(store, gid) == "archived"

    # Une fois clos, on ne peut plus l'avancer : la boucle est cassée
    assert await store.append_progress(gid, "et encore", max_step_lines=3) is False
