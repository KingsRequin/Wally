# tests/test_audit2_phaseB_donnees.py
"""Phase B du second audit : les données corrompues en base.

A2-2 — 129 alias sur 188 écrits sans préfixe `platform:` : le bloc « souvenirs
       sur un tiers » était sauté pour 69 % des pseudos connus.
A2-3 — clé `unknown:<Pseudo>` écrite en casse d'origine, cherchée en
       minuscules : les orphelins n'étaient JAMAIS migrés (31 lignes).
A2-mem — questions jamais purgées (44/45 périmées) et revenant sans fin.
"""
import inspect
import sqlite3
import time

import pytest
from unittest.mock import AsyncMock, MagicMock


# ────────────────────────────── A2-2 ──────────────────────────────
def test_un_uid_sans_namespace_est_raccroche_ou_refuse():
    from bot.intelligence import fact_extractor

    src = inspect.getsource(fact_extractor.FactExtractor._extract_facts)
    assert 'if ":" not in resolved_uid:' in src
    assert "Alias {n} ignoré : identifiant sans namespace" in src


def test_le_split_d_un_uid_prefixe_donne_bien_deux_parties():
    """La condition qui était sautée : `len(uid_parts) == 2`."""
    assert len("discord:610550333042589752".split(":", 1)) == 2
    assert len("610550333042589752".split(":", 1)) == 1


# ────────────────────────────── A2-3 ──────────────────────────────
def test_la_cle_inconnue_est_ecrite_en_minuscules():
    from bot.intelligence import fact_extractor

    src = inspect.getsource(fact_extractor.FactExtractor._extract_facts)
    assert '(entry.get("target") or "unknown").strip().lower()' in src


def test_la_migration_rend_les_orphelins_retrouvables():
    """`reassign_user('unknown:mrmakkx')` ne trouvait pas `unknown:MrMakkx`."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE atomic_facts(user_id TEXT)")
    conn.execute("INSERT INTO atomic_facts VALUES('unknown:MrMakkx')")
    conn.execute(
        "UPDATE atomic_facts SET user_id = lower(user_id) "
        "WHERE user_id LIKE 'unknown:%' AND user_id != lower(user_id)"
    )
    trouve = conn.execute(
        "SELECT count(*) FROM atomic_facts WHERE user_id = 'unknown:mrmakkx'"
    ).fetchone()[0]
    assert trouve == 1


# ────────────────────────────── questions mémoire ──────────────────────────────
@pytest.mark.asyncio
async def test_une_question_epuisee_ne_revient_plus():
    """`OR` laissait la seconde clause vraie pour toujours passé 3 tentatives."""
    from bot.db.mixins.memory import MemoryMixin

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE memory_questions(user_id TEXT, resolved INT, attempts INT,"
        " last_attempt_at REAL, priority TEXT, created_at REAL)"
    )
    vieux = time.time() - 30 * 86400
    conn.execute(
        "INSERT INTO memory_questions VALUES('u1',0,3,?, 'high', ?)", (vieux, vieux)
    )
    conn.commit()

    class _DB(MemoryMixin):
        def __init__(self):
            self._conn = _Conn(conn)

    assert await _DB().get_pending_question("u1") is None


@pytest.mark.asyncio
async def test_une_question_encore_valable_revient_bien():
    from bot.db.mixins.memory import MemoryMixin

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE memory_questions(user_id TEXT, resolved INT, attempts INT,"
        " last_attempt_at REAL, priority TEXT, created_at REAL)"
    )
    conn.execute(
        "INSERT INTO memory_questions VALUES('u1',0,1,NULL,'high',?)", (time.time(),)
    )
    conn.commit()

    class _DB(MemoryMixin):
        def __init__(self):
            self._conn = _Conn(conn)

    assert await _DB().get_pending_question("u1") is not None


@pytest.mark.asyncio
async def test_le_menage_nocturne_purge_les_questions():
    from bot.intelligence.journal import DailyJournal

    j = DailyJournal.__new__(DailyJournal)
    j._memory = MagicMock()
    j._memory.cleanup_expired_facts = AsyncMock()
    j._db = MagicMock()
    j._db.cleanup_old_questions = AsyncMock(return_value=44)
    j._sort_one_user_memory = AsyncMock()

    await j.run_memory_cleanup()
    j._db.cleanup_old_questions.assert_awaited_once()


@pytest.mark.asyncio
async def test_une_purge_en_echec_ne_bloque_pas_le_reste_du_menage():
    from bot.intelligence.journal import DailyJournal

    j = DailyJournal.__new__(DailyJournal)
    j._memory = MagicMock()
    j._memory.cleanup_expired_facts = AsyncMock()
    j._db = MagicMock()
    j._db.cleanup_old_questions = AsyncMock(side_effect=RuntimeError("table absente"))
    j._sort_one_user_memory = AsyncMock()

    await j.run_memory_cleanup()
    j._sort_one_user_memory.assert_awaited_once()


class _Conn:
    """Enveloppe async minimale autour d'une connexion sqlite3 synchrone.

    `execute()` rend un objet À LA FOIS attendable et gestionnaire de contexte
    asynchrone — c'est le contrat d'`aiosqlite.Connection.execute`, et le code
    de production s'appuie sur les deux. Le double ne portait que la moitié
    attendable : il acceptait donc du code qui FUITE (curseur jamais fermé,
    statement jamais finalisé, transaction de lecture qui reste ouverte) et
    refusait le code correct. Un double incomplet valide le mauvais usage.
    """

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        return _AttenteCurseur(self._c, sql, params)

    async def commit(self):
        self._c.commit()


class _AttenteCurseur:
    """`await conn.execute(...)` et `async with conn.execute(...)`, comme aiosqlite."""

    def __init__(self, conn, sql, params):
        self._conn, self._sql, self._params = conn, sql, params
        self._cur = None

    def _ouvrir(self):
        if self._cur is None:
            self._cur = _Cur(self._conn.execute(self._sql, self._params))
        return self._cur

    def __await__(self):
        async def _fait():
            return self._ouvrir()
        return _fait().__await__()

    async def __aenter__(self):
        return self._ouvrir()

    async def __aexit__(self, *exc):
        if self._cur is not None:
            self._cur.close()
        return False


class _Cur:
    def __init__(self, cur):
        self._cur = cur
        self.rowcount = cur.rowcount
        self.lastrowid = cur.lastrowid

    async def fetchone(self):
        return self._cur.fetchone()

    async def fetchall(self):
        return self._cur.fetchall()

    def close(self):
        self._cur.close()
