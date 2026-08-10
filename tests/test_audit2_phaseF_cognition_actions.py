# tests/test_audit2_phaseF_cognition_actions.py
"""Phase F du second audit : cognition et tâches planifiées.

A2-sleep — un `[SLEEP]` gelait la boucle jusqu'à une heure, sans réveil
           possible, et périmait les cooldowns du même tick.
A2-sched — un `schedule_type` inconnu créait une tâche « active » sans job.
A2-int   — `interval_minutes` rendu en chaîne levait un TypeError.
A2-dm    — `target.dm` était promis au modèle et lu nulle part.
A2-web   — la 2e passe après recherche web laissait une pensée orpheline ACTIVE.
"""
import asyncio
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.cognitive_loop import CognitiveLoop


# ────────────────────────────── A2-sleep ──────────────────────────────
def test_le_sleep_est_reporte_et_non_dormi_dans_le_tick():
    src = inspect.getsource(CognitiveLoop._tick)
    i = src.index('decision.action == "SLEEP"')
    bloc = src[i:i + 900]
    assert "self._sleep_hint =" in bloc
    assert "await asyncio.sleep(" not in bloc, "le tick dort encore sur place"


def test_le_sommeil_demande_est_consomme_une_seule_fois():
    src = inspect.getsource(CognitiveLoop._run)
    assert "self._sleep_hint or self._tick_interval()" in src
    assert "self._sleep_hint = None" in src


@pytest.mark.asyncio
async def test_le_sommeil_demande_reste_interruptible():
    c = CognitiveLoop.__new__(CognitiveLoop)
    c._running = True
    c._reveil = asyncio.Event()
    c._sleep_hint = 3600.0                 # une heure réclamée par le LLM
    c._wake_digest = None
    c._tick_interval = MagicMock(return_value=30)
    c._tick = AsyncMock(side_effect=lambda: setattr(c, "_running", False))

    tache = asyncio.create_task(c._run())
    await asyncio.sleep(0)
    c._reveil.set()                        # quelqu'un parle à Wally

    await asyncio.wait_for(tache, timeout=2)
    c._tick.assert_awaited()


# ────────────────────────────── A2-sched ──────────────────────────────
@pytest.mark.asyncio
async def test_un_type_de_planification_inconnu_est_refuse():
    from bot.intelligence.actions.service import ActionService

    s = ActionService.__new__(ActionService)
    s._registry = MagicMock()
    s._registry.check_permission = MagicMock(return_value=True)
    s._db = MagicMock()
    s._db.count_user_action_tasks = AsyncMock(return_value=0)

    out = await s.create(
        {"action_type": "reminder", "description": "x",
         "schedule": {"type": "daily"}},
        user_id="1", platform="discord", user_roles=["everyone"],
    )
    assert out["status"] == "error"
    assert "once" in out["message"]


def test_le_planificateur_refuse_aussi_en_aval():
    from bot.intelligence.actions.scheduler import ActionScheduler

    s = ActionScheduler.__new__(ActionScheduler)
    s._scheduler = MagicMock()
    with pytest.raises(ValueError):
        s._add_apscheduler_job(1, "weekly", {})
    s._scheduler.add_job.assert_not_called()


# ────────────────────────────── A2-int ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("valeur,attendu", [("30", "created"), (30, "created")])
async def test_un_intervalle_en_chaine_est_accepte(valeur, attendu):
    from bot.intelligence.actions.service import ActionService

    s = ActionService.__new__(ActionService)
    s._registry = MagicMock()
    s._registry.check_permission = MagicMock(return_value=True)
    s._db = MagicMock()
    s._db.count_user_action_tasks = AsyncMock(return_value=0)
    s._db.create_action_task = AsyncMock(return_value=7)
    s._scheduler = MagicMock()
    s._scheduler.schedule = AsyncMock()
    s._notify = MagicMock()

    out = await s.create(
        {"action_type": "reminder", "description": "x",
         "schedule": {"type": "interval", "interval_minutes": valeur}},
        user_id="1", platform="discord", user_roles=["everyone"],
    )
    assert out["status"] != "error", out


@pytest.mark.asyncio
async def test_un_intervalle_illisible_donne_une_erreur_claire():
    from bot.intelligence.actions.service import ActionService

    s = ActionService.__new__(ActionService)
    s._registry = MagicMock()
    s._registry.check_permission = MagicMock(return_value=True)
    s._db = MagicMock()
    s._db.count_user_action_tasks = AsyncMock(return_value=0)

    out = await s.create(
        {"action_type": "reminder", "description": "x",
         "schedule": {"type": "interval", "interval_minutes": "bientôt"}},
        user_id="1", platform="discord", user_roles=["everyone"],
    )
    assert out["status"] == "error"
    assert "Intervalle" in out["message"]


# ────────────────────────────── A2-dm ──────────────────────────────
def test_le_schema_ne_promet_plus_un_envoi_en_prive():
    from bot.intelligence.actions.service import CREATE_TOOL

    cible = CREATE_TOOL["function"]["parameters"]["properties"]["target"]
    assert "dm" not in cible["properties"]


def test_deliver_na_plus_de_parametre_mort():
    from bot.intelligence.actions.executor import ActionExecutor

    params = inspect.signature(ActionExecutor.deliver).parameters
    assert "dm" not in params


# ────────────────────────────── A2-web ──────────────────────────────
def _pensee_qui_cherche():
    """Une 1re passe dont la décision demande une recherche web."""
    acte = MagicMock(action="ACT", act_name="web_search",
                     act_args={"query": "apex saison"})
    return MagicMock(thought_fact_id=42, decisions=[acte])


def _boucle_web(trouvaille="Apex saison 26"):
    c = CognitiveLoop.__new__(CognitiveLoop)
    c._feed = None
    c._facts = MagicMock()
    c._facts.set_status = AsyncMock()
    c._reasoning = MagicMock()
    c._web_search = MagicMock(available=True)
    c._web_search.is_quota_exceeded = AsyncMock(return_value=False)
    c._web_search.search = AsyncMock(return_value=trouvaille)
    c._web_search_cooldown_ts = 0.0
    c._web_search_cooldown_s = 0.0
    return c


@pytest.mark.asyncio
async def test_la_pensee_de_premiere_passe_est_archivee():
    from bot.intelligence.memory.facts import FactStatus

    c = _boucle_web()
    seconde = MagicMock(thought_fact_id=99)
    c._reasoning.reason = AsyncMock(return_value=seconde)

    premiere = _pensee_qui_cherche()
    contexte = MagicMock()
    out = await c._maybe_web_search(contexte, premiere)

    assert out is seconde
    c._facts.set_status.assert_awaited_once_with(42, FactStatus.ARCHIVED)


@pytest.mark.asyncio
async def test_une_seconde_passe_en_echec_conserve_la_premiere():
    c = _boucle_web()
    c._reasoning.reason = AsyncMock(side_effect=RuntimeError("LLM down"))

    premiere = _pensee_qui_cherche()
    out = await c._maybe_web_search(MagicMock(), premiere)

    assert out is premiere
    c._facts.set_status.assert_not_awaited()
