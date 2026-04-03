# bot/dashboard/routes/chat.py
from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from loguru import logger

from bot.dashboard.routes.chat_auth import decode_jwt, _jwt_secret_raw
from bot.discord.handlers import _parse_react_tag

if TYPE_CHECKING:
    from bot.dashboard.state import AppState

router = APIRouter()
public_router = APIRouter()


def _extract_user_id_from_jwt(request: Request) -> str | None:
    """Returns 'discord:{discord_id}' from the Bearer JWT, or None if invalid/missing."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    payload = decode_jwt(token, _jwt_secret_raw())
    if not payload:
        return None
    return f"discord:{payload['discord_id']}"


@dataclass
class ConnectedUser:
    ws: WebSocket
    discord_id: str
    username: str
    avatar_url: str | None
    last_message: float = 0.0


_clients: dict[WebSocket, ConnectedUser] = {}
_response_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Lazy lock creation to avoid binding to wrong event loop at import time."""
    global _response_lock
    if _response_lock is None:
        _response_lock = asyncio.Lock()
    return _response_lock


async def _broadcast(data: dict) -> None:
    text = json.dumps(data)
    stale: list[WebSocket] = []
    for ws in list(_clients):
        try:
            await ws.send_text(text)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _clients.pop(ws, None)


async def _send_to(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        _clients.pop(ws, None)


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Token required")
        return

    state: AppState = ws.app.state.wally
    secret = _jwt_secret_raw()
    payload = decode_jwt(token, secret)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()

    discord_id = payload["discord_id"]
    username = payload["username"]
    avatar_url = payload.get("avatar_url")
    sender_id = f"discord:{discord_id}"

    user = ConnectedUser(ws=ws, discord_id=discord_id, username=username, avatar_url=avatar_url)
    _clients[ws] = user

    # Track connection
    conn_id = await state.db.insert_chat_connection(discord_id, username, avatar_url)
    msg_count_session = 0

    logger.info("WebChat connected: {u} ({id})", u=username, id=discord_id)

    heartbeat_task = None
    try:
        # Send today's messages only
        today = datetime.date.today().isoformat()
        history = await state.db.load_chat_history_for_day(today)
        await _send_to(ws, {"type": "history", "messages": history})

        # Start heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat(ws))

        # Message loop
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "message")

            if msg_type == "vote":
                image_id = data.get("image_id")
                if image_id:
                    voted = await state.db.toggle_gallery_vote(image_id, f"discord:{user.discord_id}")
                    await _send_to(ws, {"type": "vote_result", "image_id": image_id, "voted": voted})
                continue

            if msg_type == "edit_title":
                image_id = data.get("image_id")
                title = data.get("title", "").strip()
                if image_id and title and len(title) <= 100:
                    image = await state.db.get_gallery_image(image_id)
                    if image and image["user_id"] == f"discord:{user.discord_id}":
                        await state.db.update_gallery_title(image_id, title)
                        await _broadcast({"type": "title_updated", "image_id": image_id, "title": title})
                continue

            if msg_type != "message":
                continue

            content = (data.get("content") or "").strip()
            if not content or len(content) > 2000:
                continue

            # Cooldown check
            now = time.time()
            cooldown = state.config.web_chat.cooldown_seconds
            elapsed = now - user.last_message
            if elapsed < cooldown:
                await _send_to(ws, {
                    "type": "cooldown",
                    "remaining_seconds": round(cooldown - elapsed, 1),
                })
                continue
            user.last_message = now

            # ── Slash commands ──
            if content.startswith("/"):
                command, _, args = content.partition(" ")
                args = args.strip()
                if command == "/imagine":
                    asyncio.create_task(_handle_imagine(state, ws, user, args))
                    continue
                elif command == "/scan":
                    asyncio.create_task(_handle_scan(state, ws, user, args or None))
                    continue
                else:
                    await _send_to(ws, {"type": "system", "content": f"Commande inconnue : {command}"})
                    continue

            # Dashboard message counter
            state.message_count += 1
            state.message_count_web += 1
            msg_count_session += 1

            # Persist + broadcast user message
            msg_id = await state.db.insert_chat_message(
                sender_id, username, avatar_url, content, False, now,
            )
            user_msg = {
                "type": "message", "id": msg_id,
                "sender_id": sender_id, "username": username,
                "avatar_url": avatar_url, "content": content,
                "is_wally": False, "created_at": now,
            }
            await _broadcast(user_msg)

            # Wally response (serialized)
            asyncio.create_task(_wally_respond(state, sender_id, username, content))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebChat error for {u}: {e}", u=username, e=exc)
    finally:
        _clients.pop(ws, None)
        if heartbeat_task:
            heartbeat_task.cancel()
        try:
            await state.db.update_chat_disconnection(conn_id, msg_count_session)
        except Exception:
            pass
        logger.info("WebChat disconnected: {u}", u=username)


async def _heartbeat(ws: WebSocket) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            await ws.send_text(json.dumps({"type": "ping"}))
    except Exception:
        pass


async def _wally_respond(state: AppState, sender_id: str, username: str, content: str) -> None:
    async with _get_lock():
        try:
            await _broadcast({"type": "typing", "username": "Wally"})

            discord_raw_id = sender_id.split(":")[1]
            trust = await state.db.get_trust_score("discord", discord_raw_id)
            state.memory.append_message("web:chat", username, content, platform="discord")
            # Enregistrement dans le FactExtractor (même pattern que Discord)
            fe = getattr(state, "fact_extractor", None)
            if fe is not None:
                fe.record_message(
                    "web:chat", "discord", discord_raw_id,
                    username, content,
                )
            mem_context = await state.memory.search("discord", discord_raw_id, content)

            context_messages = await state.memory.get_context_summarized_if_needed("web:chat")
            situation = {"platform": "Web", "channel": "Chat public"}

            system_prompt = state.prompts.build_system_prompt(
                emotion_state=state.emotion.get_state(),
                memory_context=mem_context,
                situation=situation,
                persona_block=state.persona.build_prompt_block(),
                emotion_directives=state.persona.emotion_directives,
                weekday_directives=state.persona.weekday_directives,
                composite_directives=state.persona.composite_directives,
            )

            context_block = state.prompts.build_context_block(context_messages)
            user_content = f"{context_block}\n[{username}]: {content}"

            messages = [{"role": "user", "content": user_content}]

            reply = await state.primary_llm.complete(
                system_prompt, messages,
                purpose="web_response",
                user_id=sender_id,
            )

            # Strip [react:emoji] tag — web chat doesn't support reactions
            _react_emoji, reply = _parse_react_tag(reply)

            now = time.time()
            msg_id = await state.db.insert_chat_message(
                "wally", "Wally", None, reply, True, now,
            )
            await _broadcast({
                "type": "message", "id": msg_id,
                "sender_id": "wally", "username": "Wally",
                "avatar_url": None, "content": reply,
                "is_wally": True, "created_at": now,
            })

            state.memory.append_prelude("web:chat", "Wally", reply)
            state.memory.append_message("web:chat", "Wally", reply, platform="discord")

            asyncio.create_task(_post_process(state, content, sender_id, trust))

        except Exception as exc:
            logger.error("WebChat Wally response failed: {e}", e=exc)


@router.get("/api/chat/sessions")
async def chat_sessions(request: Request):
    """Return list of dates with chat messages (most recent first)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="JWT required")
    payload = decode_jwt(auth[7:], _jwt_secret_raw())
    if not payload:
        raise HTTPException(401, detail="Invalid or expired token")

    state: AppState = request.app.state.wally
    dates = await state.db.list_chat_session_dates()
    return {"dates": dates}


@router.get("/api/chat/history/{date_str}")
async def chat_history_for_day(date_str: str, request: Request):
    """Return chat messages for a specific day (YYYY-MM-DD)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="JWT required")
    payload = decode_jwt(auth[7:], _jwt_secret_raw())
    if not payload:
        raise HTTPException(401, detail="Invalid or expired token")

    # Validate date format
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, detail="Invalid date format, use YYYY-MM-DD")

    state: AppState = request.app.state.wally
    messages = await state.db.load_chat_history_for_day(date_str)
    return {"messages": messages}


@router.get("/api/chat/my-memories")
async def my_memories(request: Request):
    """Return memories for the currently authenticated chat user."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="JWT required")

    payload = decode_jwt(auth[7:], _jwt_secret_raw())
    if not payload:
        raise HTTPException(401, detail="Invalid or expired token")

    state: AppState = request.app.state.wally
    discord_id = payload["discord_id"]
    user_id = f"discord:{discord_id}"

    try:
        store = state.memory.store
        if store is None:
            return {"memories": []}

        records = await store.get_all(user_id)

        # Include accepted alias memories
        accepted_links = await state.db.list_link_proposals(status="accepted")
        alias_ids = [link["alias_id"] for link in accepted_links if link["canonical_id"] == user_id]
        for alias_id in alias_ids:
            try:
                records.extend(await store.get_all(alias_id))
            except Exception:
                pass

        # Sort by most recent first
        records.sort(
            key=lambda r: r.created_at or "",
            reverse=True,
        )
        return {"memories": [{"id": r.id, "memory": r.text} for r in records if r.text]}
    except Exception as exc:
        logger.warning("my-memories failed for {u}: {e}", u=discord_id, e=exc)
        return {"memories": []}


async def _handle_imagine(state: "AppState", ws, user, prompt: str):
    if not prompt:
        await _send_to(ws, {"type": "system", "content": "Usage : /imagine <description de l'image>"})
        return

    import uuid as _uuid
    msg_id = str(_uuid.uuid4())

    # Send "generating" embed to all connected clients
    await _broadcast({
        "type": "image_generating",
        "id": msg_id,
        "prompt": prompt,
        "loading_gif": "/api/public/loading-gif",
        "username": user.username,
        "avatar_url": user.avatar_url,
    })

    try:
        sender_id = f"discord:{user.discord_id}"

        # Generate image
        result = await state.image_client.generate_image(prompt, state.config.image_generation, sender_id)

        # Generate short title via LLM
        title = await state.secondary_llm.complete(
            "Tu es un assistant. Génère un titre court et créatif (max 6 mots) pour cette image. "
            "Réponds UNIQUEMENT avec le titre, rien d'autre.",
            [{"role": "user", "content": f"Image générée à partir du prompt : {prompt}"}],
            purpose="image_title",
        )
        title = title.strip().strip('"').strip("'")[:100]

        # Insert in gallery
        await state.db.insert_gallery_image(
            id=result["file_id"],
            title=title,
            prompt=prompt,
            revised_prompt=result.get("revised_prompt"),
            username=user.username,
            user_id=str(user.discord_id),
            platform="web",
            file_path=result["file_name"],
            model=result["model"],
            quality=result["quality"],
            size=result["size"],
            cost_usd=result["cost_usd"],
        )

        # Memory
        try:
            await state.memory.add("discord", str(user.discord_id), f"{user.username} a généré une image : {title}")
        except Exception as e:
            logger.warning("Failed to add image memory: {e}", e=e)

        # Broadcast result embed to all connected clients
        await _broadcast({
            "type": "image_result",
            "id": msg_id,
            "image_id": result["file_id"],
            "title": title,
            "prompt": prompt,
            "image_url": f"/api/public/gallery/{result['file_id']}/image",
            "username": user.username,
            "avatar_url": user.avatar_url,
            "created_at": datetime.datetime.now().isoformat(),
            "votes": 0,
            "user_voted": False,
        })

    except ValueError as e:
        # Cancel the generating embed for all clients
        await _broadcast({"type": "image_cancelled", "id": msg_id, "error": str(e)})
    except Exception as e:
        logger.error("Image generation failed in web chat: {e}", e=e)
        await _broadcast({"type": "image_cancelled", "id": msg_id, "error": "Erreur lors de la génération de l'image."})


async def _handle_scan(state: AppState, ws: WebSocket, user: ConnectedUser, query: str | None = None) -> None:
    """Handle /scan command — admin only. Scans web chat history for facts. query is reserved for future filtering."""
    # Admin check: same dashboard_token used by /api/admin/* routes
    admin_token = state.config.bot.dashboard_token
    if not admin_token:
        await _send_to(ws, {"type": "system", "content": "❌ dashboard_token non configuré."})
        return

    # Check if user is admin via Discord guild permissions
    is_admin = False
    if state.discord_bot is not None:
        for guild in state.discord_bot.guilds:
            member = guild.get_member(int(user.discord_id))
            if member and member.guild_permissions.administrator:
                is_admin = True
                break

    if not is_admin:
        await _send_to(ws, {"type": "system", "content": "❌ Réservé aux administrateurs."})
        return

    fe = getattr(state, "fact_extractor", None)
    if fe is None:
        await _send_to(ws, {"type": "system", "content": "❌ FactExtractor non disponible."})
        return

    await _send_to(ws, {"type": "system", "content": "🔍 Scan des messages web en cours…"})

    try:
        cursor = await state.db._conn.execute(
            "SELECT sender_id, username, content, created_at "
            "FROM chat_messages WHERE is_wally = 0 ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()

        if len(rows) < 2:
            await _send_to(ws, {"type": "system", "content": "⚠️ Pas assez de messages à analyser."})
            return

        msg_dicts = [
            {
                "user_id": row["sender_id"].split(":", 1)[1] if ":" in row["sender_id"] else row["sender_id"],
                "display_name": row["username"],
                "content": row["content"],
                "timestamp": row["created_at"],
            }
            for row in rows
        ]

        total_stored = 0
        batch_size = 50
        for i in range(0, len(msg_dicts), batch_size):
            batch = msg_dicts[i : i + batch_size]
            try:
                stored = await fe._extract_facts(batch, "discord", "web:chat")
                total_stored += stored
            except Exception as exc:
                logger.warning("scan-web-chat batch {i} failed: {e}", i=i, e=exc)

        await _send_to(ws, {
            "type": "system",
            "content": f"✅ Scan terminé : {total_stored} faits extraits de {len(msg_dicts)} messages.",
        })
        logger.info("/scan web-chat: {n} facts from {m} messages", n=total_stored, m=len(msg_dicts))

    except Exception as exc:
        logger.error("/scan web-chat failed: {e}", e=exc)
        await _send_to(ws, {"type": "system", "content": f"❌ Erreur: {exc}"})


@public_router.get("/memory/me")
async def get_my_memory(request: Request) -> dict:
    """Retourne les souvenirs et scores de relation de l'utilisateur connecté."""
    user_id = _extract_user_id_from_jwt(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    state = request.app.state.wally
    records = await state.memory.store.get_all(user_id)

    facts = [r.text for r in records if r.category in ("FAIT", "LANG")]
    preferences = [r.text for r in records if r.category == "PREF"]

    parts = user_id.split(":", 1)
    platform = parts[0] if len(parts) == 2 else "discord"
    raw_id = parts[1] if len(parts) == 2 else user_id

    trust = await state.db.get_trust_score(platform, raw_id)
    love = await state.db.get_love_score(platform, raw_id)

    return {
        "facts": facts,
        "preferences": preferences,
        "relation": {"trust": round(trust, 3), "love": round(love, 3)},
    }


async def _post_process(state: AppState, text: str, sender_id: str, trust: float = 0.0) -> None:
    try:
        deltas = await state.emotion.process_message(
            text, trust_score=trust, channel_id="web:chat", platform="web",
            trigger_user=sender_id,
        )
        if deltas and isinstance(deltas, dict):
            trust_delta = deltas.get("trust_delta", 0.01)
            await state.db.update_trust_score("discord", sender_id.split(":")[1], trust_delta)
    except Exception as exc:
        logger.warning("WebChat post-process failed: {e}", e=exc)
