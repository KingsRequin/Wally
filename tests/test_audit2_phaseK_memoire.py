# tests/test_audit2_phaseK_memoire.py
"""Phase K du second audit : la mémoire.

A2-lock  — le verrou d'écriture était posé sur `MemoryService.add()`, que la
           production n'emprunte pas : la course restait ouverte sur le chemin
           réel (`reconcile_candidate` → `_reconcile`).
A2-dedup — chaque écriture rapatriait tous les faits actifs de la catégorie
           (2 039 pour `wally:self`) pour les normaliser en Python, verrou tenu.
A2-enum  — le statut `dismissed` existait en base sans figurer dans l'enum :
           `FactStatus(...)` aurait levé au premier chemin sans filtre.
"""
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock


# ────────────────────────────── A2-lock ──────────────────────────────
@pytest.mark.asyncio
async def test_le_chemin_de_production_est_serialise():
    """Deux réconciliations concurrentes du même S-P-O ne doivent pas se croiser."""
    from bot.intelligence.memory.ingest import MemoryIngest

    ing = MemoryIngest.__new__(MemoryIngest)
    ing._verrous = {}
    dedans = {"max": 0, "courant": 0}

    async def _corps(cand, user_id):
        dedans["courant"] += 1
        dedans["max"] = max(dedans["max"], dedans["courant"])
        await asyncio.sleep(0)          # point de préemption
        dedans["courant"] -= 1
        return ("new", MagicMock())

    ing._reconcile_locked = _corps
    await asyncio.gather(*(ing._reconcile(MagicMock(), "discord:1") for _ in range(5)))
    assert dedans["max"] == 1, "deux écritures se sont croisées sur la même personne"


@pytest.mark.asyncio
async def test_deux_personnes_restent_paralleles():
    from bot.intelligence.memory.ingest import MemoryIngest

    ing = MemoryIngest.__new__(MemoryIngest)
    ing._verrous = {}
    ing._reconcile_locked = AsyncMock(return_value=("new", MagicMock()))

    await asyncio.gather(
        ing._reconcile(MagicMock(), "discord:1"),
        ing._reconcile(MagicMock(), "discord:2"),
    )
    assert set(ing._verrous) == {"discord:1", "discord:2"}


# ────────────────────────────── A2-dedup ──────────────────────────────
@pytest.mark.asyncio
async def test_le_doublon_est_cherche_en_sql_et_non_en_memoire(tmp_path):
    """Le pré-filtre SQL doit réduire les candidats SANS jamais rater un doublon.

    Ce test figeait auparavant la clause exacte (`length(content) = ?`), et
    verrouillait ainsi le défaut qu'il était censé décrire : `_normalize` retire
    la ponctuation, donc l'égalité stricte excluait toute phrase ponctuée —
    c'est-à-dire son propre doublon. On vérifie désormais les deux propriétés
    qui comptent, et aucune formulation.
    """
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import (
        AtomicFact, FactCategory, SQLiteFactStore, _normalize,
    )

    chemin = str(tmp_path / "k.db")
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)

    async def _ajouter(texte):
        return await store.add(
            AtomicFact(user_id="discord:1", content=texte, category=FactCategory.PREF)
        )

    ponctue = await _ajouter("Aime les chats, surtout le sien.")
    for i in range(40):
        await _ajouter(f"Court {i}")

    # 1. Il trouve — malgré la ponctuation, qui raccourcit la forme normalisée.
    cherche = _normalize("Aime les chats, surtout le sien.")
    assert await store.find_same_content("discord:1", FactCategory.PREF, cherche) == ponctue

    # 2. Il ne rapatrie pas toute la table pour autant. On compte les lignes
    #    réellement remontées, sans rien présumer de la façon de les écarter.
    rapatriees = 0
    connect_reel = store._connect

    def _espion():
        db_ctx = connect_reel()
        execute_reel = db_ctx.execute

        async def execute(sql, params=()):
            nonlocal rapatriees
            curseur = await execute_reel(sql, params)
            lignes = await curseur.fetchall()
            rapatriees += len(lignes)

            class _Rejoue:
                async def fetchall(self_inner):
                    return lignes

            return _Rejoue()

        db_ctx.execute = execute
        return db_ctx

    store._connect = _espion
    await store.find_same_content("discord:1", FactCategory.PREF, cherche)
    store._connect = connect_reel

    assert rapatriees < 41, (
        f"{rapatriees} lignes remontées sur 41 : le tri se fait en mémoire, "
        "pas en SQL — c'est ce que ce test existe pour empêcher"
    )


def test_le_service_nappelle_plus_get_by_user_pour_dedupliquer():
    from bot.intelligence.memory.service import MemoryService

    src = inspect.getsource(MemoryService.add)
    assert "find_same_content" in src
    assert "for f in await self._facts.get_by_user(" not in src


# ────────────────────────────── A2-enum ──────────────────────────────
def test_un_statut_inconnu_ne_fait_pas_lever_la_lecture():
    from bot.intelligence.memory.facts import FactStatus, SQLiteFactStore

    ligne = {
        "id": 1, "user_id": "discord:1", "content": "x", "category": "FAIT",
        "confidence": 0.9, "status": "dismissed", "emotional_context": None,
        "source": "conversation", "subject": None, "predicate": None,
        "object": None, "importance": 0.5, "support_count": 1, "origin": None,
        "expires_at": None, "scheduled_at": None,
        "created_at": "2026-08-01T00:00:00", "last_seen_at": "2026-08-01T00:00:00",
        "decay_rate": 0.01,
    }
    fait = SQLiteFactStore._row_to_fact(ligne)
    assert fait.status == FactStatus.ARCHIVED


def test_les_statuts_connus_restent_exacts():
    from bot.intelligence.memory.facts import FactStatus, SQLiteFactStore

    for valeur, attendu in (("active", FactStatus.ACTIVE),
                            ("fulfilled", FactStatus.FULFILLED),
                            ("superseded", FactStatus.SUPERSEDED)):
        ligne = {
            "id": 1, "user_id": "u", "content": "x", "category": "FAIT",
            "confidence": 0.9, "status": valeur, "emotional_context": None,
            "source": "conversation", "subject": None, "predicate": None,
            "object": None, "importance": 0.5, "support_count": 1, "origin": None,
            "expires_at": None, "scheduled_at": None,
            "created_at": "2026-08-01T00:00:00", "last_seen_at": "2026-08-01T00:00:00",
            "decay_rate": 0.01,
        }
        assert SQLiteFactStore._row_to_fact(ligne).status == attendu
