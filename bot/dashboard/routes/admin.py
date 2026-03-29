# bot/dashboard/routes/admin.py
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import asdict

# Strong refs for fire-and-forget tasks (prevents GC cancellation)
_bg_tasks: set[asyncio.Task] = set()

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.config import VALID_REASONING_EFFORTS, VALID_TEXT_VERBOSITIES, VALID_THINKING_TYPES, VALID_THINKING_EFFORTS

router = APIRouter()

_OPENAI_INCLUDE = ["gpt", "chatgpt", "o1", "o3", "o4"]
_OPENAI_EXCLUDE = ["realtime", "preview", "audio", "vision"]


@router.get("/config")
async def get_config(request: Request) -> dict:
    cfg = request.app.state.wally.config
    return {
        "bot": asdict(cfg.bot),
        "openai": asdict(cfg.openai),
        "llm": asdict(cfg.llm),
        "discord": asdict(cfg.discord),
        "twitch": asdict(cfg.twitch),
        "emotions": {k: asdict(v) for k, v in cfg.emotions.items()},
        "twitch_events": {k: asdict(v) for k, v in cfg.twitch_events.items()},
        "image_generation": asdict(cfg.image_generation),
        "overlay_image": asdict(cfg.overlay_image),
    }


@router.post("/config")
async def update_config(request: Request, body: dict) -> dict:
    """Mise à jour partielle de la config en mémoire + config.save().

    Stratégie de merge :
    - Sous-objets dict : merge champ par champ (seuls les champs fournis sont mis à jour).
    - Listes (trigger_names, channels, channel_whitelist, etc.) : remplacement intégral.
    - Champs inconnus : ignorés silencieusement.
    """
    state = request.app.state.wally
    cfg = state.config

    if "openai" in body:
        d = body["openai"]
        if "temperature" in d:
            temp = float(d["temperature"])
            if not (0.0 <= temp <= 2.0):
                raise HTTPException(status_code=400, detail="temperature must be 0.0–2.0")
            cfg.openai.temperature = temp
        if "primary_model" in d:
            cfg.openai.primary_model = str(d["primary_model"])
            cfg.llm.primary.model = str(d["primary_model"])
            state.primary_llm.model = str(d["primary_model"])
        if "secondary_model" in d:
            cfg.openai.secondary_model = str(d["secondary_model"])
            cfg.llm.secondary.model = str(d["secondary_model"])
            state.secondary_llm.model = str(d["secondary_model"])
        if "max_tokens" in d:
            cfg.openai.max_tokens = int(d["max_tokens"])
            cfg.llm.primary.max_tokens = int(d["max_tokens"])
            cfg.llm.secondary.max_tokens = int(d["max_tokens"])
            state.primary_llm.max_tokens = int(d["max_tokens"])
            state.secondary_llm.max_tokens = int(d["max_tokens"])
        if "reasoning_effort" in d:
            val = str(d["reasoning_effort"])
            if val not in VALID_REASONING_EFFORTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"reasoning_effort must be one of {VALID_REASONING_EFFORTS}",
                )
            cfg.openai.reasoning_effort = val
            cfg.llm.primary.reasoning_effort = val
            cfg.llm.secondary.reasoning_effort = val
            if hasattr(state.primary_llm, "reasoning_effort"):
                state.primary_llm.reasoning_effort = val
            if hasattr(state.secondary_llm, "reasoning_effort"):
                state.secondary_llm.reasoning_effort = val
        if "text_verbosity" in d:
            val = str(d["text_verbosity"])
            if val not in VALID_TEXT_VERBOSITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"text_verbosity must be one of {VALID_TEXT_VERBOSITIES}",
                )
            cfg.openai.text_verbosity = val
            cfg.llm.primary.text_verbosity = val
            cfg.llm.secondary.text_verbosity = val
            if hasattr(state.primary_llm, "text_verbosity"):
                state.primary_llm.text_verbosity = val
            if hasattr(state.secondary_llm, "text_verbosity"):
                state.secondary_llm.text_verbosity = val

    if "llm" in body:
        llm_data = body["llm"]
        needs_restart = False
        if "primary" in llm_data:
            p = llm_data["primary"]
            if "provider" in p and p["provider"] != cfg.llm.primary.provider:
                cfg.llm.primary.provider = p["provider"]
                needs_restart = True
            if "model" in p:
                cfg.llm.primary.model = p["model"]
                cfg.openai.primary_model = p["model"]
                state.primary_llm.model = p["model"]
            # Claude thinking settings
            if "thinking_type" in p:
                val = str(p["thinking_type"])
                if val not in VALID_THINKING_TYPES:
                    raise HTTPException(status_code=400, detail=f"thinking_type must be one of {VALID_THINKING_TYPES}")
                cfg.llm.primary.thinking_type = val
                if hasattr(state.primary_llm, "thinking_type"):
                    state.primary_llm.thinking_type = val
            if "thinking_effort" in p:
                val = str(p["thinking_effort"])
                if val not in VALID_THINKING_EFFORTS:
                    raise HTTPException(status_code=400, detail=f"thinking_effort must be one of {VALID_THINKING_EFFORTS}")
                cfg.llm.primary.thinking_effort = val
                if hasattr(state.primary_llm, "thinking_effort"):
                    state.primary_llm.thinking_effort = val
            if "thinking_budget_tokens" in p:
                val = int(p["thinking_budget_tokens"])
                if not (1000 <= val <= 128000):
                    raise HTTPException(status_code=400, detail="thinking_budget_tokens must be 1000–128000")
                cfg.llm.primary.thinking_budget_tokens = val
                if hasattr(state.primary_llm, "thinking_budget_tokens"):
                    state.primary_llm.thinking_budget_tokens = val
        if "secondary" in llm_data:
            s = llm_data["secondary"]
            if "provider" in s and s["provider"] != cfg.llm.secondary.provider:
                cfg.llm.secondary.provider = s["provider"]
                needs_restart = True
            if "model" in s:
                cfg.llm.secondary.model = s["model"]
                cfg.openai.secondary_model = s["model"]
                state.secondary_llm.model = s["model"]
        if needs_restart:
            # Provider changed — recreate LLM clients in-place
            from bot.core.llm import create_llm_client
            if "primary" in llm_data and llm_data["primary"].get("provider") != type(state.primary_llm).__name__.lower().replace("llmclient", ""):
                state.primary_llm = create_llm_client(cfg.llm.primary, state.db)
                # Update bot references
                if state.discord_bot:
                    state.discord_bot.llm = state.primary_llm
                    if hasattr(state.discord_bot, "journal"):
                        state.discord_bot.journal._llm = state.primary_llm
                if state.twitch_bot:
                    state.twitch_bot.llm = state.primary_llm
            if "secondary" in llm_data and llm_data["secondary"].get("provider") != type(state.secondary_llm).__name__.lower().replace("llmclient", ""):
                state.secondary_llm = create_llm_client(cfg.llm.secondary, state.db)
                if state.discord_bot:
                    state.discord_bot.llm_secondary = state.secondary_llm
                    if hasattr(state.discord_bot, "journal"):
                        state.discord_bot.journal._llm_secondary = state.secondary_llm
                if state.twitch_bot:
                    state.twitch_bot.llm_secondary = state.secondary_llm
                # Update shared services that hold a reference to secondary LLM
                state.memory.set_openai_client(state.secondary_llm)
                state.emotion.set_openai_client(state.secondary_llm)
                if state.fact_extractor:
                    state.fact_extractor._openai = state.secondary_llm

    if "bot" in body:
        d = body["bot"]
        if "language_default" in d:
            cfg.bot.language_default = str(d["language_default"])
        if "journal_time" in d:
            cfg.bot.journal_time = str(d["journal_time"])
        if "context_window_size" in d:
            cfg.bot.context_window_size = int(d["context_window_size"])
        if "context_token_threshold" in d:
            cfg.bot.context_token_threshold = int(d["context_token_threshold"])
        if "journal_channel_id" in d:
            cfg.bot.journal_channel_id = d["journal_channel_id"]
        if "dashboard_token" in d:
            cfg.bot.dashboard_token = str(d["dashboard_token"]) or None
        if "trigger_names" in d:
            cfg.bot.trigger_names = list(d["trigger_names"])  # liste : remplacement intégral
        if "cost_alert_threshold" in d:
            val = float(d["cost_alert_threshold"])
            if val <= 0:
                raise HTTPException(status_code=400, detail="cost_alert_threshold must be > 0")
            cfg.bot.cost_alert_threshold = val
        if "spontaneous_discord_enabled" in d:
            cfg.bot.spontaneous_discord_enabled = bool(d["spontaneous_discord_enabled"])
        if "spontaneous_twitch_enabled" in d:
            cfg.bot.spontaneous_twitch_enabled = bool(d["spontaneous_twitch_enabled"])
        if "spontaneous_probability" in d:
            cfg.bot.spontaneous_probability = float(d["spontaneous_probability"])
        if "spontaneous_passion_probability" in d:
            cfg.bot.spontaneous_passion_probability = float(d["spontaneous_passion_probability"])
        if "spontaneous_cooldown_seconds" in d:
            cfg.bot.spontaneous_cooldown_seconds = int(d["spontaneous_cooldown_seconds"])
        if "notification_guild_id" in d:
            cfg.bot.notification_guild_id = int(d["notification_guild_id"]) if d["notification_guild_id"] else None
        if "notification_channel_id" in d:
            cfg.bot.notification_channel_id = int(d["notification_channel_id"]) if d["notification_channel_id"] else None

    if "discord" in body:
        d = body["discord"]
        if "anger_trigger_threshold" in d:
            cfg.discord.anger_trigger_threshold = int(d["anger_trigger_threshold"])
        if "timeout_minutes" in d:
            cfg.discord.timeout_minutes = int(d["timeout_minutes"])
        if "channel_filter_mode" in d:
            cfg.discord.channel_filter_mode = str(d["channel_filter_mode"])
        if "channel_whitelist" in d:
            cfg.discord.channel_whitelist = list(d["channel_whitelist"])  # liste
        if "channel_blacklist" in d:
            cfg.discord.channel_blacklist = list(d["channel_blacklist"])  # liste
        if "spam_detection" in d:
            sd = d["spam_detection"]
            spam = cfg.discord.spam_detection
            if "enabled" in sd:
                spam.enabled = bool(sd["enabled"])
            if "max_messages" in sd:
                val = int(sd["max_messages"])
                if not (3 <= val <= 50):
                    raise HTTPException(400, "max_messages must be 3-50")
                spam.max_messages = val
            if "window_seconds" in sd:
                val = int(sd["window_seconds"])
                if not (30 <= val <= 600):
                    raise HTTPException(400, "window_seconds must be 30-600")
                spam.window_seconds = val
            if "mute_minutes" in sd:
                val = int(sd["mute_minutes"])
                if not (1 <= val <= 60):
                    raise HTTPException(400, "mute_minutes must be 1-60")
                spam.mute_minutes = val
            if "spam_anger_delta" in sd:
                val = float(sd["spam_anger_delta"])
                if not (0.01 <= val <= 0.2):
                    raise HTTPException(400, "spam_anger_delta must be 0.01-0.2")
                spam.spam_anger_delta = val
            if "exempt_channels" in sd:
                spam.exempt_channels = [int(c) for c in sd["exempt_channels"]]

    if "twitch" in body:
        d = body["twitch"]
        if "guest_channels" in d:
            cfg.twitch.guest_channels = list(d["guest_channels"])  # liste : remplacement intégral
        if "cooldown_seconds" in d:
            cfg.twitch.cooldown_seconds = int(d["cooldown_seconds"])

    if "emotions" in body:
        for name, d in body["emotions"].items():
            if name not in cfg.emotions:
                continue
            if "decay_lambda" in d:
                lam = float(d["decay_lambda"])
                if lam <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"decay_lambda for {name} must be > 0",
                    )
                cfg.emotions[name].decay_lambda = lam
            if "boredom_rise_per_hour" in d:
                cfg.emotions[name].boredom_rise_per_hour = float(d["boredom_rise_per_hour"])

    # Image generation config
    if "image_generation" in body:
        d = body["image_generation"]
        ig = cfg.image_generation
        if "model" in d:
            ig.model = str(d["model"])
        if "quality" in d:
            val = str(d["quality"])
            if val not in ("low", "medium", "high", "auto"):
                raise HTTPException(400, "quality must be low/medium/high/auto")
            ig.quality = val
        if "size" in d:
            val = str(d["size"])
            if val not in ("1024x1024", "1024x1536", "1536x1024", "auto"):
                raise HTTPException(400, "size must be 1024x1024/1024x1536/1536x1024/auto")
            ig.size = val
        if "background" in d:
            ig.background = str(d["background"])
        if "format" in d:
            val = str(d["format"])
            if val not in ("png", "jpeg", "webp"):
                raise HTTPException(400, "format must be png/jpeg/webp")
            ig.format = val
        if "daily_limit" in d:
            ig.daily_limit = int(d["daily_limit"])
        if "per_user_limit" in d:
            ig.per_user_limit = int(d["per_user_limit"])

    # Overlay image config
    if "overlay_image" in body:
        d = body["overlay_image"]
        oi = cfg.overlay_image
        if "command" in d:
            oi.command = str(d["command"])
        if "display_duration" in d:
            val = int(d["display_duration"])
            if not (5 <= val <= 60):
                raise HTTPException(400, "display_duration must be 5-60")
            oi.display_duration = val
        if "animation_in" in d:
            oi.animation_in = str(d["animation_in"])
        if "animation_out" in d:
            oi.animation_out = str(d["animation_out"])
        if "animation_duration" in d:
            val = float(d["animation_duration"])
            if not (0.5 <= val <= 3.0):
                raise HTTPException(400, "animation_duration must be 0.5-3.0")
            oi.animation_duration = val
        if "random_filter" in d:
            val = str(d["random_filter"])
            if val not in ("all", "top", "recent"):
                raise HTTPException(400, "random_filter must be all/top/recent")
            oi.random_filter = val
        if "enabled" in d:
            oi.enabled = bool(d["enabled"])

    cfg.save()
    return {"status": "saved"}


@router.get("/openai/models")
async def get_openai_models(request: Request) -> dict:
    """Liste les modèles OpenAI filtrés selon les règles du cahier des charges.

    Inclut : gpt, chatgpt, o1, o3, o4
    Exclut : realtime, preview, audio, vision

    Fallback sur les modèles configurés en cas d'erreur API.
    """
    state = request.app.state.wally
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        models_page = await client.models.list()
        filtered = sorted([
            m.id for m in models_page.data
            if any(kw in m.id for kw in _OPENAI_INCLUDE)
            and not any(kw in m.id for kw in _OPENAI_EXCLUDE)
        ])
        return {"models": filtered}
    except Exception as exc:
        logger.warning("Failed to list OpenAI models: {e}", e=exc)
        return {"models": [
            state.config.llm.primary.model,
            state.config.llm.secondary.model,
        ]}


_CLAUDE_INCLUDE = ["claude"]
_CLAUDE_EXCLUDE = ["beta", "preview"]


@router.get("/claude/models")
async def get_claude_models(request: Request) -> dict:
    """Liste les modèles Claude disponibles via l'API Anthropic.

    Fallback sur les modèles configurés en cas d'erreur API.
    """
    state = request.app.state.wally
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        models_page = await client.models.list(limit=100)
        filtered = sorted([
            m.id for m in models_page.data
            if any(kw in m.id for kw in _CLAUDE_INCLUDE)
            and not any(kw in m.id for kw in _CLAUDE_EXCLUDE)
        ])
        return {"models": filtered}
    except Exception as exc:
        logger.warning("Failed to list Claude models: {e}", e=exc)
        return {"models": [
            state.config.llm.primary.model,
            state.config.llm.secondary.model,
        ]}


_TWITCH_LOGIN_RE = re.compile(r'^[a-z0-9_]{1,25}$')


@router.post("/twitch/channels")
async def add_twitch_channel(request: Request, body: dict) -> dict:
    """Ajoute une chaîne Twitch invitée.

    body = {"name": "streameurxyz"}
    Retourne {"broadcaster_id": "..."} en cas de succès.
    """
    name = str(body.get("name", "")).strip().lower()
    if not _TWITCH_LOGIN_RE.match(name):
        raise HTTPException(status_code=400, detail="Nom de chaîne invalide")
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    result = await state.twitch_bot.add_guest_channel(name)
    if result == "already_added":
        raise HTTPException(status_code=409, detail="Chaîne déjà ajoutée")
    if result is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable sur Twitch")
    return {"broadcaster_id": result}


@router.delete("/twitch/channels/{name}")
async def remove_twitch_channel(request: Request, name: str) -> dict:
    """Supprime une chaîne Twitch invitée."""
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    await state.twitch_bot.remove_guest_channel(name.lower())
    return {"status": "removed"}


@router.get("/twitch/channels")
async def list_twitch_channels(request: Request) -> list[dict]:
    """Liste les chaines Twitch invitees avec statut IRC et live."""
    state = request.app.state.wally
    if state.twitch_bot is None:
        raise HTTPException(status_code=503, detail="Twitch non disponible")
    bot = state.twitch_bot
    return [
        {
            "name": name,
            "broadcaster_id": bid,
            "irc_connected": bot.get_channel(name) is not None,
            "live": bot._channel_was_live.get(name, False),
        }
        for name, bid in bot._channel_ids.items()
    ]


@router.post("/overlay/toggle")
async def toggle_overlay(request: Request) -> dict:
    """Bascule la visibilité de l'overlay OBS en temps réel et persiste dans config."""
    state = request.app.state.wally
    state.overlay_visible = not state.overlay_visible
    state.config.web_chat.overlay_visible = state.overlay_visible
    state.config.save()
    return {"visible": state.overlay_visible}


@router.get("/overlay/status")
async def overlay_status(request: Request) -> dict:
    """Retourne l'état actuel de l'overlay."""
    state = request.app.state.wally
    return {"visible": state.overlay_visible}


@router.get("/notification-channels")
async def list_notification_channels(request: Request) -> dict:
    """Liste les serveurs et salons textuels disponibles pour les notifications."""
    state = request.app.state.wally
    if state.discord_bot is None:
        return {"guilds": []}

    import discord
    guilds = []
    for guild in state.discord_bot.guilds:
        channels = []
        for ch in guild.text_channels:
            channels.append({"id": ch.id, "name": ch.name})
        guilds.append({
            "id": guild.id,
            "name": guild.name,
            "channels": channels,
        })
    return {"guilds": guilds}


@router.get("/chat-connections")
async def list_chat_connections(request: Request, limit: int = 50) -> dict:
    """Liste les connexions récentes au chat web."""
    state = request.app.state.wally
    limit = max(1, min(limit, 200))
    connections = await state.db.list_chat_connections(limit)
    return {"connections": connections}


@router.post("/overlay-image/test")
async def test_overlay_image(request: Request):
    state = request.app.state.wally
    image = await state.db.get_random_gallery_image(state.config.overlay_image.random_filter)
    if not image:
        raise HTTPException(404, "No images in gallery to test")
    cfg = state.config.overlay_image
    payload = {
        "image_url": f"/api/public/gallery/{image['id']}/image",
        "title": image.get("title") or "",
        "username": image["username"],
        "display_duration": cfg.display_duration,
        "animation_in": cfg.animation_in,
        "animation_out": cfg.animation_out,
        "animation_duration": cfg.animation_duration,
    }
    # Vider la queue pour que le dernier test gagne toujours
    while not state.overlay_image_queue.empty():
        try:
            state.overlay_image_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    state.overlay_image_queue.put_nowait(payload)
    return {"status": "triggered", "image_id": image["id"]}


@router.get("/bot/status")
async def get_bot_status(request: Request) -> dict:
    state = request.app.state.wally
    discord_online = (
        state.discord_bot is not None
        and state.discord_bot.is_ready()
    )
    twitch_online = (
        state.twitch_bot is not None
        and getattr(state.twitch_bot, "_eventsub_client", None) is not None
    )
    return {
        "discord": "connected" if discord_online else "disconnected",
        "twitch": "connected" if twitch_online else "disconnected",
    }


@router.post("/bot/discord/stop")
async def stop_discord(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Discord bot not configured")
    if bot.is_closed():
        return {"ok": True, "message": "already stopped"}
    await bot.close()
    logger.info("Discord bot stopped via dashboard")
    return {"ok": True}


@router.post("/bot/discord/start")
async def start_discord(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.discord_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Discord bot not configured")
    if not bot.is_closed():
        return {"ok": True, "message": "already running"}
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="DISCORD_TOKEN not set")
    task = asyncio.create_task(bot.start(token))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    logger.info("Discord bot started via dashboard")
    return {"ok": True}


@router.post("/bot/twitch/stop")
async def stop_twitch(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.twitch_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Twitch bot not configured")
    if getattr(bot, "_closed", False):
        return {"ok": True, "message": "already stopped"}
    await bot.close()
    logger.info("Twitch bot stopped via dashboard")
    return {"ok": True}


@router.post("/bot/twitch/start")
async def start_twitch(request: Request) -> dict:
    state = request.app.state.wally
    bot = state.twitch_bot
    if bot is None:
        raise HTTPException(status_code=404, detail="Twitch bot not configured")
    if not getattr(bot, "_closed", True):
        return {"ok": True, "message": "already running"}
    task = asyncio.create_task(bot.start())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    logger.info("Twitch bot started via dashboard")
    return {"ok": True}


@router.get("/prompts")
async def list_prompts(request: Request) -> dict:
    from pathlib import Path
    app_dir = Path(__file__).parents[3]
    persona_dir = app_dir / "bot" / "persona"
    prompts_dir = persona_dir / "prompts"

    persona_files = ["SOUL.md", "IDENTITY.md", "VOICE.md", "EXEMPLES.md",
                     "EMOTIONS.md", "WEEKDAYS.md", "SECONDARIES.md", "COMPOSITES.md"]
    persona = {}
    for fname in persona_files:
        p = persona_dir / fname
        persona[fname] = p.read_text() if p.exists() else ""

    system_prompts = {}
    if prompts_dir.exists():
        for p in sorted(prompts_dir.glob("*.md")):
            system_prompts[p.name] = p.read_text()

    return {"persona": persona, "system_prompts": system_prompts}


@router.post("/prompts/persona/{filename}")
async def save_persona_file(filename: str, request: Request) -> dict:
    from pathlib import Path
    import re
    if not re.match(r'^[A-Z_]+\.md$', filename):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    body = await request.json()
    content = body.get("content", "")
    persona_dir = Path(__file__).parents[3] / "bot" / "persona"
    (persona_dir / filename).write_text(content)
    # Reload persona service if available
    bot = getattr(request.app.state, "wally", None)
    if bot and hasattr(bot, "persona"):
        try:
            bot.persona.reload()
        except Exception:
            pass
    return {"ok": True}


@router.post("/prompts/system/{filename}")
async def save_system_prompt(filename: str, request: Request) -> dict:
    from pathlib import Path
    import re
    if not re.match(r'^[\w_-]+\.md$', filename):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    body = await request.json()
    content = body.get("content", "")
    prompts_dir = Path(__file__).parents[3] / "bot" / "persona" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / filename).write_text(content)
    return {"ok": True}


@router.post("/bot/restart")
async def restart_container(request: Request) -> dict:
    logger.warning("Container restart requested via dashboard")

    async def _do_restart():
        await asyncio.sleep(1)
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "restart", "wally",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Restart failed: {}", stderr.decode())

    task = asyncio.create_task(_do_restart())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"ok": True, "message": "Restart initiated"}


# ── Persistent notes ─────────────────────────────────────────────────────────

@router.get("/notes")
async def get_notes(request: Request) -> dict:
    db = request.app.state.wally.db
    notes = await db.get_persistent_notes()
    return {"notes": notes}


@router.put("/notes/{note_id}")
async def update_note(note_id: int, request: Request) -> dict:
    body = await request.json()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title et content requis")
    db = request.app.state.wally.db
    await db.upsert_persistent_note(title, content)
    return {"ok": True}


@router.post("/notes")
async def create_note(request: Request) -> dict:
    body = await request.json()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title et content requis")
    db = request.app.state.wally.db
    await db.upsert_persistent_note(title, content)
    return {"ok": True}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int, request: Request) -> dict:
    db = request.app.state.wally.db
    async with db._conn.execute("SELECT title FROM persistent_notes WHERE id = ?", (note_id,)) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Note introuvable")
    deleted = await db.delete_persistent_note(row["title"])
    return {"ok": deleted}
