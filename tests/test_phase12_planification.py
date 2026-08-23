# tests/test_phase12_planification.py
"""Phase 12 de l'audit du 2026-08-10 : planification et portée des actions.

M31 — `misfire_grace_time` à 1 s (défaut APScheduler) sur 4 jobs de journal
      dont 3 à la même seconde : 7 journées manquantes, sans une trace.
M32 — même défaut sur les rappels : un pic de charge à l'instant du tir et la
      tâche `once` n'était JAMAIS délivrée.
M33 — `resume()` ne remettait pas `consecutive_failures` à 0 : re-pause au
      premier échec au lieu des trois annoncés.
M34 — `send_message_to_channel` validait la permission sur le serveur d'origine
      puis balayait tous les serveurs du bot.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock


# ────────────────────────────── M31 ──────────────────────────────
def test_les_jobs_du_journal_tolerent_le_retard():
    from bot.intelligence import journal

    assert journal._TOLERANCE_RETARD["misfire_grace_time"] >= 600
    assert journal._TOLERANCE_RETARD["coalesce"] is True
    src = inspect.getsource(journal.DailyJournal.start)
    # Les quatre jobs (journal, ménage, consolidation, modélisation).
    assert src.count("**_TOLERANCE_RETARD") == 4


@pytest.mark.asyncio
async def test_le_journal_passe_bien_la_tolerance_a_apscheduler():
    from bot.intelligence.journal import DailyJournal

    config = MagicMock()
    config.bot.journal_channel_id = 1
    config.bot.journal_time = "21:00"
    j = DailyJournal(config, MagicMock(), MagicMock(), MagicMock(), MagicMock())
    planificateur = MagicMock()
    j.start(planificateur)

    assert planificateur.add_job.call_count >= 2
    for appel in planificateur.add_job.call_args_list:
        assert appel.kwargs.get("misfire_grace_time", 1) > 1, appel.kwargs.get("id")


# ────────────────────────────── M32 ──────────────────────────────
def test_les_rappels_tolerent_le_retard():
    from bot.intelligence.actions import scheduler

    assert scheduler._TOLERANCE_RETARD["misfire_grace_time"] >= 600
    src = inspect.getsource(scheduler.ActionScheduler._add_apscheduler_job)
    # Les trois types : once, interval, cron.
    assert src.count("**_TOLERANCE_RETARD") == 3


def test_une_tache_once_en_retard_est_quand_meme_planifiee():
    from datetime import datetime, timedelta

    from bot.intelligence.actions.scheduler import ActionScheduler, TZ

    s = ActionScheduler.__new__(ActionScheduler)
    s._scheduler = MagicMock()
    passe = (datetime.now(TZ) + timedelta(minutes=5)).isoformat()
    s._add_apscheduler_job(1, "once", {"run_at": passe})

    kwargs = s._scheduler.add_job.call_args.kwargs
    assert kwargs["misfire_grace_time"] >= 600


# ────────────────────────────── M33 ──────────────────────────────
@pytest.mark.asyncio
async def test_reprendre_une_tache_remet_le_compteur_d_echecs_a_zero():
    from bot.intelligence.actions.scheduler import ActionScheduler

    s = ActionScheduler.__new__(ActionScheduler)
    s._scheduler = MagicMock()
    s._notify = MagicMock()
    s._db = MagicMock()
    s._db.get_action_task = AsyncMock(return_value={
        "id": 7, "status": "paused", "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "consecutive_failures": 3,
    })
    s._db.update_action_task = AsyncMock()

    await s.resume(7)

    kwargs = s._db.update_action_task.await_args.kwargs
    assert kwargs["status"] == "active"
    assert kwargs["consecutive_failures"] == 0


# ────────────────────────────── M34 ──────────────────────────────
#
# Le bornage au serveur d'origine se teste maintenant en ENVOYANT le message et
# en regardant où il part : `tests/test_action_handlers.py`, en particulier
# `test_le_message_part_dans_le_salon_du_SERVEUR_D_ORIGINE` et sa contre-épreuve.
#
# Ce qui était ici cherchait `"guildes = [guilde_origine]"` dans le source de
# `main.py`. Ça couvrait une correction de SÉCURITÉ par la présence d'une chaîne
# de caractères : vert devant n'importe quelle logique contenant ces mots, et
# muet sur ce que le code fait. Le handler a depuis quitté `main.py`
# (`bot/intelligence/actions/handlers.py`), ce qui aurait de toute façon rendu
# l'assertion fausse pour la mauvaise raison.
