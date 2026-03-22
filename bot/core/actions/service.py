"""ActionService — LLM facade exposing tool definitions for action tasks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

TZ = ZoneInfo("Europe/Paris")

MAX_TASKS_PER_USER = 10
MIN_INTERVAL_MINUTES = 5
PAST_GRACE_SECONDS = 30

CREATE_TOOL = {
    "type": "function",
    "function": {
        "name": "create_action_task",
        "description": "Créer une tâche planifiée (rappel, recherche web, génération d'image...)",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["reminder", "web_search", "image_generate"],
                    "description": "Type d'action à exécuter",
                },
                "description": {
                    "type": "string",
                    "description": "Description en langage naturel de la tâche",
                },
                "payload": {
                    "type": "object",
                    "description": "Paramètres de l'action (message, query, prompt...)",
                },
                "schedule": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["once", "interval", "cron"]},
                        "run_at": {"type": "string", "description": "ISO datetime (Europe/Paris) pour once"},
                        "interval_minutes": {"type": "integer", "description": "Intervalle en minutes (min 5)"},
                        "cron_hour": {"type": "integer"},
                        "cron_minute": {"type": "integer"},
                        "cron_day_of_week": {"type": "string", "description": "mon,tue,wed,thu,fri,sat,sun"},
                        "max_executions": {"type": ["integer", "null"], "description": "Max exécutions (null=infini)"},
                    },
                    "required": ["type"],
                },
                "target": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["discord", "twitch", "web"]},
                        "channel_id": {"type": "string"},
                        "dm": {"type": "boolean", "description": "Envoyer en DM au créateur"},
                    },
                },
            },
            "required": ["action_type", "description"],
            "additionalProperties": False,
        },
    },
}

CANCEL_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_action_task",
        "description": "Annuler une tâche planifiée par ID ou par description",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID de la tâche à annuler"},
                "search_query": {"type": "string", "description": "Recherche par description"},
            },
            "additionalProperties": False,
        },
    },
}

LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "list_action_tasks",
        "description": "Lister les tâches planifiées",
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "enum": ["active", "paused", "all"], "default": "active"},
                "own_only": {"type": "boolean", "default": True, "description": "Mes tâches uniquement"},
            },
            "additionalProperties": False,
        },
    },
}


class ActionService:
    def __init__(self, registry, scheduler, db) -> None:
        self._registry = registry
        self._scheduler = scheduler
        self._db = db

    def get_tool_definitions(self) -> list[dict]:
        return [CREATE_TOOL, CANCEL_TOOL, LIST_TOOL]

    async def execute_tool(
        self, name: str, args: dict, user_id: str, platform: str,
        user_roles: list[str], channel_id: str | None = None,
    ) -> dict:
        if name == "create_action_task":
            return await self.create(args, user_id, platform, user_roles, channel_id)
        elif name == "cancel_action_task":
            return await self.cancel(
                task_id=args.get("task_id"),
                search_query=args.get("search_query"),
                user_id=user_id, platform=platform, user_roles=user_roles,
            )
        elif name == "list_action_tasks":
            return await self.list_tasks(
                user_id=user_id, platform=platform,
                status_filter=args.get("status_filter", "active"),
                own_only=args.get("own_only", True),
                user_roles=user_roles,
            )
        return {"status": "error", "message": f"Unknown tool: {name}"}

    async def create(
        self, task_data: dict, user_id: str, platform: str,
        user_roles: list[str], channel_id: str | None = None,
    ) -> dict:
        action_type = task_data.get("action_type", "")

        # Permission check
        if not self._registry.check_permission(action_type, platform, user_roles):
            return {"status": "denied", "message": f"Action {action_type} non autorisée pour votre rôle."}

        # Rate limit
        count = await self._db.count_user_action_tasks(user_id, platform)
        if count >= MAX_TASKS_PER_USER:
            return {"status": "rate_limited", "message": f"Maximum {MAX_TASKS_PER_USER} tâches actives atteint."}

        # Validate schedule
        schedule = task_data.get("schedule")
        if not schedule:
            return {
                "status": "need_more_info",
                "missing": ["schedule"],
                "message": "Je dois savoir quand exécuter cette tâche.",
            }

        schedule_type = schedule.get("type", "")
        missing = []

        if schedule_type == "once":
            run_at = schedule.get("run_at")
            if not run_at:
                missing.append("schedule.run_at")
            else:
                try:
                    run_at_dt = datetime.fromisoformat(run_at)
                    if run_at_dt.tzinfo is None:
                        run_at_dt = run_at_dt.replace(tzinfo=TZ)
                    grace = datetime.now(TZ) - timedelta(seconds=PAST_GRACE_SECONDS)
                    if run_at_dt < grace:
                        return {"status": "error", "message": "L'heure spécifiée est dans le passé."}
                except ValueError:
                    return {"status": "error", "message": "Format de date invalide."}

        elif schedule_type == "interval":
            interval = schedule.get("interval_minutes")
            if not interval:
                missing.append("schedule.interval_minutes")
            elif interval < MIN_INTERVAL_MINUTES:
                return {"status": "error", "message": f"Intervalle minimum: {MIN_INTERVAL_MINUTES} minutes."}

        elif schedule_type == "cron":
            if "cron_hour" not in schedule and "cron_minute" not in schedule:
                missing.append("schedule.cron_hour")
                missing.append("schedule.cron_minute")

        if missing:
            return {
                "status": "need_more_info",
                "missing": missing,
                "message": "Il me manque des informations pour planifier cette tâche.",
            }

        # Default target to originating channel
        target = task_data.get("target", {})
        target_platform = target.get("platform", platform)
        target_channel = target.get("channel_id", channel_id)

        # Build schedule_spec
        spec: dict = {}
        if schedule_type == "once":
            spec["run_at"] = schedule["run_at"]
        elif schedule_type == "interval":
            spec["minutes"] = schedule["interval_minutes"]
        elif schedule_type == "cron":
            if "cron_hour" in schedule:
                spec["hour"] = schedule["cron_hour"]
            if "cron_minute" in schedule:
                spec["minute"] = schedule["cron_minute"]
            if "cron_day_of_week" in schedule:
                spec["day_of_week"] = schedule["cron_day_of_week"]

        payload = task_data.get("payload", {})
        max_executions = schedule.get("max_executions")
        if schedule_type == "once" and max_executions is None:
            max_executions = 1

        task_id = await self._scheduler.schedule(
            action_type=action_type,
            description=task_data.get("description", ""),
            creator_id=user_id,
            creator_platform=platform,
            target_channel=target_channel,
            target_platform=target_platform,
            payload=json.dumps(payload),
            schedule_type=schedule_type,
            schedule_spec=json.dumps(spec),
            max_executions=max_executions,
        )

        return {
            "status": "created",
            "task_id": task_id,
            "description": task_data.get("description", ""),
            "next_run_at": spec.get("run_at"),
        }

    async def cancel(
        self, task_id: int | None = None, search_query: str | None = None,
        user_id: str = "", platform: str = "", user_roles: list[str] | None = None,
    ) -> dict:
        if task_id is not None:
            task = await self._db.get_action_task(task_id)
            if not task:
                return {"status": "not_found", "message": "Tâche introuvable."}
            is_admin = "admin" in (user_roles or [])
            if not is_admin and (task["creator_id"] != user_id or task["creator_platform"] != platform):
                return {"status": "denied", "message": "Cette tâche ne vous appartient pas."}
            await self._scheduler.cancel(task_id)
            return {"status": "cancelled", "task": {"id": task["id"], "description": task["description"]}}

        if search_query:
            results = await self._db.search_action_tasks(search_query, user_id, platform)
            if len(results) == 0:
                return {"status": "not_found", "message": "Aucune tâche correspondante trouvée."}
            if len(results) == 1:
                await self._scheduler.cancel(results[0]["id"])
                return {"status": "cancelled", "task": {"id": results[0]["id"], "description": results[0]["description"]}}
            return {
                "status": "ambiguous",
                "candidates": [{"id": r["id"], "description": r["description"]} for r in results],
            }

        return {"status": "error", "message": "task_id ou search_query requis."}

    # --- Dashboard facade methods (avoid private access from routes) ---

    async def pause_task(self, task_id: int) -> None:
        await self._scheduler.pause(task_id)

    async def resume_task(self, task_id: int) -> None:
        await self._scheduler.resume(task_id)

    async def execute_task_now(self, task_id: int) -> str:
        return await self._scheduler.execute_now(task_id)

    async def update_permission(self, action_type: str, platform: str, min_role: str) -> None:
        await self._registry.update_permission(action_type, platform, min_role)

    async def set_action_enabled(self, action_type: str, enabled: bool) -> None:
        await self._registry.set_enabled(action_type, enabled)

    async def list_tasks(
        self, user_id: str = "", platform: str = "",
        status_filter: str = "active", own_only: bool = True,
        user_roles: list[str] | None = None,
    ) -> dict:
        is_admin = "admin" in (user_roles or [])
        creator_id = user_id if (own_only or not is_admin) else None
        creator_platform = platform if creator_id else None

        rows = await self._db.list_action_tasks(
            status=status_filter if status_filter != "all" else None,
            creator_id=creator_id,
            creator_platform=creator_platform,
        )
        tasks = [
            {
                "id": r["id"],
                "action_type": r["action_type"],
                "description": r["description"],
                "status": r["status"],
                "next_run_at": r.get("next_run_at"),
                "execution_count": r.get("execution_count", 0),
                "max_executions": r.get("max_executions"),
            }
            for r in rows
        ]
        return {"status": "ok", "tasks": tasks}
