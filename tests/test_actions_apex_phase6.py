"""Phase 6 : planificateur d'actions et perception Apex."""
from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock

from bot.intelligence.actions.scheduler import ActionScheduler


def _scheduler(tasks=None):
    db = MagicMock()
    db.get_active_action_tasks = AsyncMock(return_value=tasks or [])
    db.update_action_task = AsyncMock()
    db.get_action_task = AsyncMock()
    sched = ActionScheduler.__new__(ActionScheduler)
    sched._db = db
    sched._scheduler = MagicMock()
    sched._notify = MagicMock()
    return sched, db


# ── reload_all ne peut plus faire avorter le démarrage ───────────────────────
#
# La boucle n'avait aucune garde par tâche, et elle tourne au boot AVANT
# `shared_scheduler.start()`, depuis un `main.py` non protégé. Un
# `schedule_spec` vide — la colonne a un `DEFAULT '{}'` — suffisait à faire
# remonter l'exception jusqu'en haut : plus aucune tâche replanifiée, et le bot
# ne démarrait pas.

async def test_une_tache_bancale_ne_fait_pas_tomber_le_rechargement():
    mauvaise = {"id": 1, "schedule_type": "once", "schedule_spec": "",
                "next_run_at": None}
    bonne = {"id": 2, "schedule_type": "interval",
             "schedule_spec": json.dumps({"minutes": 30}), "next_run_at": None}
    sched, db = _scheduler([mauvaise, bonne])

    await sched.reload_all()                       # ne lève pas

    # La bonne a bien été planifiée malgré la mauvaise.
    assert sched._scheduler.add_job.call_count == 1


async def test_une_tache_interval_voit_son_echeance_rafraichie():
    """Le trigger `interval` repart de `now + minutes` au `add_job`, mais
    `next_run_at` gardait la valeur d'avant l'arrêt : la phase glissait à chaque
    rebuild, et l'échéance affichée était périmée, souvent dans le passé."""
    tache = {"id": 7, "schedule_type": "interval",
             "schedule_spec": json.dumps({"minutes": 30}),
             "next_run_at": "2020-01-01T00:00:00"}
    sched, db = _scheduler([tache])

    await sched.reload_all()

    ecrits = [c for c in db.update_action_task.await_args_list
              if "next_run_at" in c.kwargs]
    assert ecrits, "next_run_at n'a pas été rafraîchi"
    assert not ecrits[0].kwargs["next_run_at"].startswith("2020")


# ── Une tâche cron sait dire quand elle repasse ──────────────────────────────

def test_next_run_at_est_calcule_pour_le_cron():
    """Aucune branche ne couvrait `cron` : la fonction retombait sur None, écrit
    tel quel en base. `next_run_at` restait perpétuellement NULL pour toute
    tâche récurrente, et `ORDER BY next_run_at` les faisait remonter en tête."""
    sched, _ = _scheduler()
    prochaine = sched._compute_next_run("cron", {"hour": 9, "minute": 0})

    assert prochaine is not None
    assert prochaine.startswith("20")              # une date ISO, pas None


def test_un_spec_cron_bancal_ne_leve_pas():
    sched, _ = _scheduler()
    assert sched._compute_next_run("cron", {"hour": "n'importe quoi"}) is None


# ── Une tâche `once` ne devient pas un zombie ────────────────────────────────

def test_once_force_max_executions_a_un():
    """Le schéma de l'outil expose `max_executions` librement. Avec `once` +
    `max_executions: 3`, `_on_job_executed` voyait `1 >= 3` faux, recalculait
    `next_run_at` = la date DÉJÀ passée et laissait `active` — alors que le job
    `date` est consommé. Tâche active à vie, jamais déclenchée, occupant une des
    10 places du quota."""
    source = inspect.getsource(
        __import__("bot.intelligence.actions.service", fromlist=["x"]).ActionService.create
    )
    assert 'if schedule_type == "once":' in source
    assert "max_executions is None" not in source.split('if schedule_type == "once":')[1][:200]


async def test_une_tache_once_est_completee_meme_avec_un_compteur_plus_haut():
    tache = {"id": 3, "schedule_type": "once", "schedule_spec": "{}",
             "execution_count": 0, "max_executions": 3, "status": "active"}
    sched, db = _scheduler()
    db.get_action_task = AsyncMock(return_value=tache)
    sched._remove_job = MagicMock()

    await sched._on_job_executed(3, "ok")

    assert db.update_action_task.await_args.kwargs["status"] == "completed"


# ── Le point de départ Apex n'est pas partagé entre deux lives ───────────────

def _watcher(live=True, live_id="2026-08-09T20:00:00Z", db=None):
    from bot.core.apex.watcher import ApexWatcher

    return ApexWatcher(
        service=MagicMock(), account=("Azrael", "PC"),
        is_live=lambda: live, live_id=lambda: live_id, db=db,
    )


async def test_le_depart_dun_autre_live_est_ignore():
    """Un process arrêté avant la fin du live A et redémarré pendant le live B
    rechargeait le départ de A : Wally annonçait des « +N kills depuis le début
    du live » cumulant deux sessions — de la donnée fausse, à l'écran."""
    db = MagicMock()
    db.get_state = AsyncMock(return_value=json.dumps(
        {"live": "live-A", "stats": {"kills": 100}}
    ))
    w = _watcher(live_id="live-B", db=db)

    assert await w._load_baseline() == {}


async def test_le_depart_du_meme_live_est_repris():
    db = MagicMock()
    db.get_state = AsyncMock(return_value=json.dumps(
        {"live": "live-A", "stats": {"kills": 100}}
    ))
    w = _watcher(live_id="live-A", db=db)

    assert await w._load_baseline() == {"kills": 100}


async def test_lancien_format_plat_est_jete():
    """Sans identité de live, on ne peut pas savoir d'où il vient."""
    db = MagicMock()
    db.get_state = AsyncMock(return_value=json.dumps({"kills": 100}))

    assert await _watcher(db=db)._load_baseline() == {}


async def test_hors_live_on_necrit_pas_a_chaque_tour():
    """La branche écrivait en base à chaque tour hors live : ~960 commits par
    jour sur le fichier SQLite partagé, pour rien."""
    db = MagicMock()
    db.set_state = AsyncMock()
    db.get_state = AsyncMock(return_value="{}")
    w = _watcher(live=False, db=db)
    w._baseline = {}

    await w.tick()
    await w.tick()

    db.set_state.assert_not_awaited()


# ── Deux corrections de forme ────────────────────────────────────────────────

def test_le_graphique_du_journal_est_rendu_hors_boucle():
    """L'import de matplotlib puis le rendu bloquaient tout le process pendant
    plusieurs centaines de ms à quelques secondes, à la minute précise où trois
    autres jobs lourds sont planifiés."""
    from pathlib import Path

    source = Path("bot/intelligence/journal.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(_generate_emotion_chart" in source


async def test_le_limiteur_apex_utilise_lhorloge_injectee():
    """Le constructeur accepte une horloge, utilisée pour le TTL du cache, mais
    `_rate_limit` lisait l'horloge réelle : les deux divergeaient dès qu'un test
    en fournissait une factice. Couture d'injection incomplète, donc trompeuse.
    """
    from bot.core.apex.client import ApexClient

    horloge = {"t": 1000.0}
    client = ApexClient(api_key="k", now=lambda: horloge["t"])

    await client._rate_limit()
    assert client._last_request == 1000.0      # l'horloge INJECTÉE, pas la vraie

    horloge["t"] = 5000.0
    await client._rate_limit()
    assert client._last_request == 5000.0
