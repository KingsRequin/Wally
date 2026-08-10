# tests/test_audit2_phaseO_performance.py
"""Phase O du second audit : performance mesurée.

A2-fts  — `_known_facts_hint` passe la conversation ENTIÈRE en requête : 200
          termes en OR remontaient 10 885 lignes sur 14 388, le MATCH ne
          filtrait plus rien.
A2-sys  — `read_host_metrics()` appelé EN DIRECT sur le chemin de chaque
          message, alors qu'il fait des lectures sysfs synchrones.
A2-apex — la même ligne de liaison lue deux fois par requête ; client httpx
          reconstruit à chaque appel.
A2-mem  — `/memory/users` faisait ses `fetch_user` Discord en série.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.memory.facts import _fts_match_query


# ────────────────────────────── A2-fts ──────────────────────────────
def test_une_conversation_entiere_ne_devient_pas_une_requete_de_200_termes():
    from bot.intelligence.memory.facts import _FTS_MAX_TERMS

    conversation = " ".join(f"motnumero{i}" for i in range(200))
    requete = _fts_match_query(conversation)
    assert requete.count(" OR ") + 1 == _FTS_MAX_TERMS


def test_une_requete_courte_reste_intacte():
    assert _fts_match_query("apex saison rank") == '"apex" OR "saison" OR "rank"'


def test_la_selection_est_reproductible():
    """Deux appels identiques doivent produire la même requête."""
    conversation = " ".join(f"terme{i:03d}" for i in range(120))
    assert _fts_match_query(conversation) == _fts_match_query(conversation)


def test_les_termes_les_plus_longs_sont_privilegies():
    requete = _fts_match_query("a bb " + " ".join(f"tres_long_terme_{i}" for i in range(30)))
    assert "tres_long_terme_0" in requete


# ────────────────────────────── A2-sys ──────────────────────────────
def test_le_prompt_passe_par_le_cache_des_metriques():
    from bot.intelligence import prompts

    src = inspect.getsource(prompts)
    assert "cached_host_metrics()" in src
    assert "read_host_metrics()" not in src


def test_les_metriques_hote_ne_sont_pas_relues_a_chaque_appel():
    from bot.core import system_info

    appels = {"n": 0}

    def _faux():
        appels["n"] += 1
        return "CPU 42°C"

    system_info._host_cache = (0.0, None)
    original = system_info.read_host_metrics
    system_info.read_host_metrics = _faux
    try:
        for _ in range(10):
            system_info.cached_host_metrics()
    finally:
        system_info.read_host_metrics = original
    assert appels["n"] == 1, "sysfs relu à chaque message"


# ────────────────────────────── A2-apex ──────────────────────────────
@pytest.mark.asyncio
async def test_la_liaison_apex_nest_lue_quune_fois():
    from bot.core.apex.service import ApexLegendsService

    svc = ApexLegendsService.__new__(ApexLegendsService)
    svc._db = MagicMock()
    svc._db.apex_find_by_display_name = AsyncMock(
        return_value={"apex_name": "xeforce_", "apex_platform": "PC", "uid": "42"}
    )

    lien = await svc._lien("xeforce_", None)
    assert lien["uid"] == "42"
    assert svc._db.apex_find_by_display_name.await_count == 1


def test_les_deux_resolutions_partagent_la_meme_lecture():
    from bot.core.apex.service import ApexLegendsService

    for methode in (ApexLegendsService._resolve, ApexLegendsService._resolve_uid):
        src = inspect.getsource(methode)
        assert "await self._lien(" in src
        assert "apex_find_by_display_name" not in src


def test_le_client_http_apex_est_reutilise():
    from bot.core.apex.client import ApexClient

    src = inspect.getsource(ApexClient._fetch)
    assert "async with httpx.AsyncClient" not in src
    assert "self._http_client()" in src


# ────────────────────────────── A2-mem ──────────────────────────────
def test_la_resolution_des_pseudos_est_parallelisee_et_bornee():
    from bot.dashboard.routes import memory

    src = inspect.getsource(memory._resolve_missing_usernames)
    assert "asyncio.Semaphore(" in src
    assert "await asyncio.gather(" in src
