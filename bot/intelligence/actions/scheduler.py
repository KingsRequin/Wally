"""ActionScheduler — SQLite persistence + apscheduler job management."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

TZ = ZoneInfo("Europe/Paris")


class ActionScheduler:
    def __init__(self, db, executor, apscheduler, on_change=None) -> None:
        self._db = db
        self._executor = executor
        self._scheduler = apscheduler
        self._on_change = on_change

    def _notify(self, event_type: str, task_id: int, **extra) -> None:
        if self._on_change:
            try:
                self._on_change(event_type, task_id, extra if extra else None)
            except Exception:
                pass

    async def schedule(self, action_type: str, description: str, creator_id: str,
                       creator_platform: str, target_channel: str | None,
                       target_platform: str | None, payload: str, schedule_type: str,
                       schedule_spec: str, max_executions: int | None) -> int:
        now = datetime.now(TZ).isoformat()
        spec = json.loads(schedule_spec)
        next_run = self._compute_next_run(schedule_type, spec)
        task_id = await self._db.insert_action_task(
            action_type=action_type, description=description,
            creator_id=creator_id, creator_platform=creator_platform,
            target_channel=target_channel, target_platform=target_platform,
            payload=payload, schedule_type=schedule_type, schedule_spec=schedule_spec,
            max_executions=max_executions, status="active",
            created_at=now, updated_at=now, next_run_at=next_run,
        )
        self._add_apscheduler_job(task_id, schedule_type, spec)
        logger.info("Scheduled action task {} ({}): {}", task_id, action_type, description)
        self._notify("created", task_id, description=description, action_type=action_type)
        return task_id

    async def cancel(self, task_id: int) -> None:
        now = datetime.now(TZ).isoformat()
        self._remove_job(task_id)
        await self._db.update_action_task(task_id, status="cancelled", updated_at=now)
        logger.info("Cancelled action task {}", task_id)
        self._notify("cancelled", task_id)

    async def pause(self, task_id: int) -> None:
        now = datetime.now(TZ).isoformat()
        self._remove_job(task_id)
        await self._db.update_action_task(task_id, status="paused", updated_at=now)
        logger.info("Paused action task {}", task_id)
        self._notify("paused", task_id)

    async def resume(self, task_id: int) -> None:
        task = await self._db.get_action_task(task_id)
        if not task or task["status"] != "paused":
            return
        now = datetime.now(TZ).isoformat()
        spec = json.loads(task["schedule_spec"])
        next_run = self._compute_next_run(task["schedule_type"], spec)
        self._add_apscheduler_job(task_id, task["schedule_type"], spec)
        await self._db.update_action_task(task_id, status="active", updated_at=now, next_run_at=next_run)
        logger.info("Resumed action task {}", task_id)
        self._notify("resumed", task_id)

    async def execute_now(self, task_id: int) -> str:
        task = await self._db.get_action_task(task_id)
        if not task:
            return "Task not found"
        return await self._run_task(task)

    async def reload_all(self) -> None:
        tasks = await self._db.get_active_action_tasks()
        now = datetime.now(TZ)
        missed_count = 0
        scheduled_count = 0
        ignored_count = 0
        for task in tasks:
            # Garde PAR TÂCHE : la boucle n'en avait aucune, et elle tourne au
            # démarrage, avant `shared_scheduler.start()`, depuis un `main.py`
            # non protégé. `json.loads(task["schedule_spec"])` sur une valeur
            # vide, ou `datetime.fromisoformat(spec.get("run_at", ""))` dans
            # `_add_apscheduler_job`, suffisait donc à faire avorter le
            # DÉMARRAGE du bot — et la colonne a un `DEFAULT '{}'`, donc une
            # ligne insérée hors de `ActionService.create` produit ce cas.
            try:
                next_run_str = task["next_run_at"]
                is_past = False
                if next_run_str:
                    try:
                        next_run_dt = datetime.fromisoformat(next_run_str)
                        if next_run_dt.tzinfo is None:
                            next_run_dt = next_run_dt.replace(tzinfo=TZ)
                        is_past = next_run_dt < now
                    except (ValueError, TypeError):
                        is_past = False
                if task["schedule_type"] == "once" and is_past:
                    await self._db.update_action_task(task["id"], status="missed", updated_at=now.isoformat())
                    missed_count += 1
                else:
                    # `or "{}"` comme dans `_on_job_executed`, qui était déjà
                    # défensif ici alors que ce chemin ne l'était pas.
                    spec = json.loads(task["schedule_spec"] or "{}")
                    self._add_apscheduler_job(task["id"], task["schedule_type"], spec)
                    # Une tâche `interval` repart de `now + minutes` au moment du
                    # `add_job`, mais `next_run_at` gardait la valeur d'avant
                    # l'arrêt : la phase glissait à chaque rebuild, et le
                    # dashboard comme l'outil LLM affichaient une échéance
                    # périmée, souvent dans le passé, pour une tâche pourtant
                    # bien planifiée.
                    if task["schedule_type"] in ("interval", "cron"):
                        recalcule = self._compute_next_run(task["schedule_type"], spec)
                        if recalcule:
                            await self._db.update_action_task(
                                task["id"], next_run_at=recalcule,
                                updated_at=now.isoformat(),
                            )
                    scheduled_count += 1
            except Exception as exc:  # noqa: BLE001 — une ligne bancale n'empêche pas le boot
                ignored_count += 1
                logger.warning(
                    "Tâche {id} non replanifiée ({t}) : {e}",
                    id=task.get("id"), t=task.get("schedule_type"), e=exc,
                )
        logger.info(
            "Reloaded action tasks: {} scheduled, {} missed, {} ignorées",
            scheduled_count, missed_count, ignored_count,
        )

    async def _on_job_executed(self, task_id: int, result: str) -> None:
        task = await self._db.get_action_task(task_id)
        if not task:
            return
        now = datetime.now(TZ).isoformat()
        new_count = task["execution_count"] + 1
        updates: dict = {"execution_count": new_count, "consecutive_failures": 0,
                         "last_run_at": now, "updated_at": now}
        max_exec = task["max_executions"]
        # Une tâche `once` est terminée par définition, quel que soit le
        # compteur : son job apscheduler de type `date` est consommé et retiré,
        # donc la laisser `active` produit un zombie qui ne repartira jamais tout
        # en occupant une place du quota. Ceinture, en plus de la normalisation
        # à la création — une ligne insérée autrement passerait ici aussi.
        if task["schedule_type"] == "once" or (max_exec is not None and new_count >= max_exec):
            updates["status"] = "completed"
            self._remove_job(task_id)
            logger.info("Action task {} completed ({}/{} executions)", task_id, new_count, max_exec)
            self._notify("completed", task_id)
        else:
            spec = json.loads(task["schedule_spec"] or "{}")
            next_run = self._compute_next_run(task["schedule_type"], spec)
            updates["next_run_at"] = next_run
            self._notify("executed", task_id)
        await self._db.update_action_task(task_id, **updates)

    async def _on_job_failed(self, task_id: int, error: str) -> None:
        task = await self._db.get_action_task(task_id)
        if not task:
            return
        now = datetime.now(TZ).isoformat()
        failures = task["consecutive_failures"] + 1
        updates: dict = {"consecutive_failures": failures, "last_error": error,
                         "last_run_at": now, "updated_at": now}
        if task["schedule_type"] == "once":
            updates["status"] = "missed"
            self._remove_job(task_id)
            logger.warning("Once task {} marked missed after failure: {}", task_id, error)
            self._notify("failed", task_id, error=error)
        elif failures >= 3:
            updates["status"] = "paused"
            self._remove_job(task_id)
            logger.warning("Action task {} auto-paused after {} failures: {}", task_id, failures, error)
            self._notify("failed", task_id, error=error, auto_paused=True)
        else:
            self._notify("failed", task_id, error=error)
        await self._db.update_action_task(task_id, **updates)

    async def _run_task(self, task: dict) -> str:
        try:
            result = await self._executor.execute(task)
            await self._on_job_executed(task["id"], result)
            return result
        except Exception as e:
            error_msg = str(e)
            await self._on_job_failed(task["id"], error_msg)
            return f"Error: {error_msg}"

    def _add_apscheduler_job(self, task_id: int, schedule_type: str, spec: dict) -> None:
        job_id = f"action_task_{task_id}"
        if schedule_type == "once":
            run_at = datetime.fromisoformat(spec.get("run_at", ""))
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=TZ)
            self._scheduler.add_job(self._trigger_job, "date", run_date=run_at,
                                    args=[task_id], id=job_id, replace_existing=True)
        elif schedule_type == "interval":
            self._scheduler.add_job(self._trigger_job, "interval", minutes=spec.get("minutes", 30),
                                    args=[task_id], id=job_id, replace_existing=True)
        elif schedule_type == "cron":
            cron_kwargs = {}
            for key in ("hour", "minute", "day_of_week"):
                if key in spec:
                    cron_kwargs[key] = spec[key]
            self._scheduler.add_job(self._trigger_job, "cron", args=[task_id],
                                    id=job_id, replace_existing=True, timezone=TZ, **cron_kwargs)

    async def _trigger_job(self, task_id: int) -> None:
        task = await self._db.get_action_task(task_id)
        if not task or task["status"] != "active":
            return
        await self._run_task(task)

    def _remove_job(self, task_id: int) -> None:
        job_id = f"action_task_{task_id}"
        try:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        except Exception:
            pass

    def _compute_next_run(self, schedule_type: str, spec: dict) -> str | None:
        now = datetime.now(TZ)
        if schedule_type == "once":
            return spec.get("run_at")
        elif schedule_type == "interval":
            return (now + timedelta(minutes=spec.get("minutes", 30))).isoformat()
        elif schedule_type == "cron":
            # Aucune branche ne couvrait `cron` : la fonction retombait sur None,
            # écrit tel quel en base à la création, au `resume` et après chaque
            # exécution. `next_run_at` restait donc perpétuellement NULL pour
            # toute tâche récurrente : ni le dashboard ni l'outil LLM ne savaient
            # dire quand un rappel quotidien repasserait. Et `ORDER BY
            # next_run_at` faisait remonter ces tâches en tête, toujours.
            try:
                from apscheduler.triggers.cron import CronTrigger

                cron_kwargs = {k: spec[k] for k in ("hour", "minute", "day_of_week") if k in spec}
                prochaine = CronTrigger(timezone=TZ, **cron_kwargs).get_next_fire_time(None, now)
                return prochaine.isoformat() if prochaine else None
            except Exception as exc:  # noqa: BLE001 — un spec cron bancal n'est pas fatal
                logger.warning("next_run_at cron incalculable ({s}): {e}", s=spec, e=exc)
                return None
        return None
