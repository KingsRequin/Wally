"""La réconciliation d'un pseudo vers son compte ne doit rien détruire.

`_extract_facts` pose l'alias `unknown:<pseudo> → discord:<id>` PUIS lance la
réconciliation. Comme `MemoryService._user_id()` termine par
`self._alias_cache.get(raw, raw)`, toute lecture ou suppression passant par le
service et visant « unknown:<pseudo> » désignait en réalité le compte canonique.

L'ancienne réconciliation enchaînait donc, sur ce même compte : relecture de
tous ses faits, réinsertion en un blob, puis `delete_user_memories` — un
`DELETE` sec, pas un archivage. Tout ce que Wally savait de la personne
disparaissait, blob compris, à chaque extraction résolvant un alias avec une
confiance ≥ 0,8 — et les vrais orphelins n'étaient jamais migrés.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.fact_extractor import FactExtractor
from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from bot.intelligence.memory.service import MemoryService


@pytest.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "facts.db")
    await create_v2_tables(path)
    return path


async def _add(store: SQLiteFactStore, uid: str, content: str) -> int:
    return await store.add(
        AtomicFact(user_id=uid, content=content, category=FactCategory.FAIT)
    )


def _extractor(memory: MemoryService) -> FactExtractor:
    return FactExtractor(config=MagicMock(), memory=memory, llm=MagicMock(), db=None)


async def test_reassign_deplace_sans_rien_perdre(db_path):
    store = SQLiteFactStore(db_path)
    await _add(store, "unknown:azrael", "joue à Apex tous les soirs")
    await _add(store, "unknown:azrael", "déteste le café")
    await _add(store, "discord:610", "habite à Lyon")

    moved = await store.reassign_user("unknown:azrael", "discord:610")

    assert moved == 2
    contents = {f.content for f in await store.get_by_user("discord:610")}
    assert contents == {
        "joue à Apex tous les soirs",
        "déteste le café",
        "habite à Lyon",          # le fait déjà là est INTACT
    }
    assert await store.get_by_user("unknown:azrael") == []


async def test_reassign_refuse_de_travailler_sur_lui_meme(db_path):
    store = SQLiteFactStore(db_path)
    await _add(store, "discord:610", "habite à Lyon")
    assert await store.reassign_user("discord:610", "discord:610") == 0
    assert len(await store.get_by_user("discord:610")) == 1


async def test_la_reconciliation_ne_vide_pas_le_compte_canonique(db_path):
    """Le scénario exact du bug, joué avec l'alias déjà posé — comme en prod."""
    memory = MemoryService(config=MagicMock())
    memory.set_embedding_backend(db_path)
    store = memory.fact_store

    await _add(store, "discord:610", "habite à Lyon")
    await _add(store, "discord:610", "a un chat qui s'appelle Nyx")
    await _add(store, "unknown:azrael", "adore les ramen")

    # Ce que fait l'appelant juste avant de lancer la réconciliation.
    memory.add_alias(alias_id="unknown:azrael", canonical_id="discord:610")

    await _extractor(memory)._reconcile_orphan_facts("azrael", "discord:610")

    contents = {f.content for f in await store.get_by_user("discord:610")}
    assert contents == {
        "habite à Lyon",                # AVANT le correctif : effacé
        "a un chat qui s'appelle Nyx",  # AVANT le correctif : effacé
        "adore les ramen",              # AVANT le correctif : jamais migré
    }


async def test_la_reconciliation_sans_orphelin_ne_touche_a_rien(db_path):
    memory = MemoryService(config=MagicMock())
    memory.set_embedding_backend(db_path)
    store = memory.fact_store
    await _add(store, "discord:610", "habite à Lyon")
    memory.add_alias(alias_id="unknown:inconnu", canonical_id="discord:610")

    await _extractor(memory)._reconcile_orphan_facts("inconnu", "discord:610")

    assert len(await store.get_by_user("discord:610")) == 1
