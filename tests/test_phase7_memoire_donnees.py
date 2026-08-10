# tests/test_phase7_memoire_donnees.py
"""Phase 7 de l'audit du 2026-08-10 : mémoire et données.

M1 — deux formats de date dans les mêmes colonnes (24 955 lignes en aware,
     le reste en naïf) : toute soustraction directe lève `TypeError`.
M2 — `target: null` (autorisé par le schéma) faisait lever les deux branches.
M3 — `get_missing_regulars` filtrait sur `memory_count`, colonne morte en V2.
M4 — `added_during` calculé, rangé, mais absent du retour.
"""
import inspect
import sqlite3
import time
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock


# ────────────────────────────── M1 ──────────────────────────────
def test_le_service_ecrit_des_dates_naives():
    """Un seul point d'écriture en aware suffisait à polluer toute la table."""
    from bot.intelligence.memory import service

    src = inspect.getsource(service.MemoryService.add)
    assert "datetime.now(timezone.utc)" not in src
    assert "datetime.utcnow()" in src


@pytest.mark.asyncio
async def test_le_fait_ajoute_porte_une_date_soustractible():
    from bot.intelligence.memory.service import MemoryService

    svc = MemoryService.__new__(MemoryService)
    svc._alias_cache = {}
    svc._add_locks = {}
    svc._facts = MagicMock()
    # La déduplication passe maintenant par une requête SQL ciblée plutôt que
    # par un rapatriement de tous les faits actifs de la catégorie.
    svc._facts.find_same_content = AsyncMock(return_value=None)
    capture = {}
    svc._retrieval = MagicMock()

    async def _add_fact(f):
        capture["fait"] = f

    svc._retrieval.add_fact = _add_fact
    await svc.add("discord", "42", "aime les chats")

    fait = capture["fait"]
    assert fait.created_at.tzinfo is None
    # Le test du défaut : mélanger aware et naïf lève TypeError.
    (datetime.utcnow() - fait.created_at)


# ────────────────────────────── M2 ──────────────────────────────
def test_un_target_null_ne_produit_pas_un_identifiant_none():
    """`.get(clé, défaut)` ne s'applique QU'À une clé absente, pas à `null`."""
    entry = {"target": None}
    assert (entry.get("target", "unknown")) is None      # l'ancien code
    assert (entry.get("target") or "unknown") == "unknown"  # le nouveau


def test_le_code_utilise_bien_la_forme_or():
    from bot.intelligence import fact_extractor

    src = inspect.getsource(fact_extractor)
    assert 'entry.get("target", "unknown")' not in src
    assert 'entry.get("target") or "unknown"' in src


# ────────────────────────────── M3 ──────────────────────────────
@pytest.mark.asyncio
async def test_les_habitues_absents_comptent_les_faits_reels():
    """`memory_count` annonçait 23 souvenirs pour 0 fait réel."""
    from bot.db.mixins.social import SocialMixin

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE memory_users(user_id TEXT, username TEXT,
                                  last_updated REAL, memory_count INTEGER);
        CREATE TABLE atomic_facts(user_id TEXT, status TEXT);
        CREATE TABLE daily_log(author TEXT);
    """)
    vieux = time.time() - 40 * 86400
    # Compteur gonflé, aucun fait réel → ne doit PAS remonter.
    conn.execute("INSERT INTO memory_users VALUES('discord:1','lornitorinqu',?,23)", (vieux,))
    # Compteur à zéro, mais 6 faits réels → doit remonter.
    conn.execute("INSERT INTO memory_users VALUES('discord:2','vraie_habituee',?,0)", (vieux,))
    for _ in range(6):
        conn.execute("INSERT INTO atomic_facts VALUES('discord:2','active')")
    conn.commit()

    class _DB(SocialMixin):
        async def fetch_all(self, query, params=()):
            return conn.execute(query, params).fetchall()

    out = await _DB().get_missing_regulars(min_memories=5, min_days_absent=30)
    noms = [r["username"].lower() for r in out]
    assert "vraie_habituee" in noms
    assert "lornitorinqu" not in noms


# ────────────────────────────── M4 ──────────────────────────────
@pytest.mark.asyncio
async def test_les_messages_arrives_pendant_le_resume_sont_rendus():
    from bot.intelligence.memory.service import MemoryService

    svc = MemoryService.__new__(MemoryService)
    svc._openai = MagicMock()
    svc._config = MagicMock()
    svc._config.bot.context_token_threshold = 100

    anciens = [{"author": "a", "content": "x" * 4000, "timestamp": 100.0 + i} for i in range(40)]
    pendant = {"author": "b", "content": "arrivé pendant", "timestamp": 999.0}

    async def _resume(messages):
        # Un message arrive dans la fenêtre pendant l'await du résumé.
        svc._context_windows["c1"] = anciens + [pendant]
        return "résumé"

    svc._context_windows = {"c1": list(anciens)}
    svc.get_context = lambda ch: svc._context_windows.get(ch, [])
    svc._summarize_messages = _resume

    out = await svc.get_context_summarized_if_needed("c1")

    contenus = [m["content"] for m in out]
    assert "résumé" in contenus
    assert "arrivé pendant" in contenus, "le message arrivé pendant le résumé est perdu"
