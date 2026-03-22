"""Dashboard API routes for action task management."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str | None = None,
    platform: str | None = None,
    creator: str | None = None,
    action_type: str | None = None,
) -> dict:
    state = request.app.state.wally
    rows = await state.db.list_action_tasks(
        status=status, creator_id=creator, action_type=action_type,
    )
    return {"tasks": [dict(r) for r in rows]}


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    task = await state.db.get_action_task(task_id)
    if not task:
        return {"error": "not found"}
    return {"task": task}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.cancel(task_id=task_id, user_id="", platform="", user_roles=["admin"])
    return {"status": "ok"}


@router.post("/tasks/{task_id}/pause")
async def pause_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.pause_task(task_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/resume")
async def resume_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    await state.action_service.resume_task(task_id)
    return {"status": "ok"}


@router.post("/tasks/{task_id}/execute")
async def execute_task(request: Request, task_id: int) -> dict:
    state = request.app.state.wally
    result = await state.action_service.execute_task_now(task_id)
    return {"status": "ok", "result": result}


@router.get("/permissions")
async def list_permissions(request: Request) -> dict:
    state = request.app.state.wally
    perms = await state.db.list_action_permissions()
    return {"permissions": [dict(p) for p in perms]}


@router.put("/permissions/{action_type}")
async def update_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    svc = state.action_service

    if "min_role_discord" in body:
        await svc.update_permission(action_type, "discord", body["min_role_discord"])
    if "min_role_twitch" in body:
        await svc.update_permission(action_type, "twitch", body["min_role_twitch"])
    if "enabled" in body:
        await svc.set_action_enabled(action_type, bool(body["enabled"]))

    return {"status": "ok"}
