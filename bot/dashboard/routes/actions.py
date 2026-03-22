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


@router.get("/discord-roles")
async def discord_roles(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        return {"guilds": []}
    guilds = []
    for guild in bot.guilds:
        roles = [{"id": "everyone", "name": "everyone", "color": "#99aab5"}]
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
            if role.is_default() or role.is_bot_managed():
                continue
            color = f"#{role.color.value:06x}" if role.color.value else "#99aab5"
            roles.append({"id": str(role.id), "name": role.name, "color": color})
        guilds.append({"id": str(guild.id), "name": guild.name, "roles": roles})
    return {"guilds": guilds}


@router.get("/permissions")
async def list_permissions(request: Request) -> dict:
    state = request.app.state.wally
    perms = await state.db.list_action_permissions()
    result = []
    for r in perms:
        p = dict(r)
        discord_roles = await state.action_service._registry.get_discord_roles_for_action(r["action_type"])
        p["discord_roles"] = discord_roles
        result.append(p)
    return {"permissions": result}


@router.put("/permissions/{action_type}/discord")
async def update_discord_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    guild_id = body.get("guild_id", "")
    role_ids = body.get("role_ids", [])
    if not guild_id:
        return {"error": "guild_id required"}
    # Build roles list with names from bot cache
    roles = []
    for rid in role_ids:
        roles.append({"role_id": rid, "role_name": _resolve_role_name(state, guild_id, rid)})
    await state.action_service._registry.update_discord_permission(action_type, guild_id, roles)
    return {"status": "ok"}


@router.put("/permissions/{action_type}")
async def update_permission(request: Request, action_type: str) -> dict:
    state = request.app.state.wally
    body = await request.json()
    svc = state.action_service

    if "min_role_twitch" in body:
        await svc.update_permission(action_type, "twitch", body["min_role_twitch"])
    if "enabled" in body:
        await svc.set_action_enabled(action_type, bool(body["enabled"]))

    return {"status": "ok"}


def _resolve_role_name(state, guild_id: str, role_id: str) -> str:
    if role_id == "everyone":
        return "everyone"
    bot = state.discord_bot
    if bot is None:
        return ""
    try:
        guild = bot.get_guild(int(guild_id))
    except (ValueError, TypeError):
        return ""
    if guild is None:
        return ""
    role = guild.get_role(int(role_id))
    return role.name if role else ""
