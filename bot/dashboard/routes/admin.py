# bot/dashboard/routes/admin.py
from __future__ import annotations

import os
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.config import VALID_REASONING_EFFORTS, VALID_TEXT_VERBOSITIES

router = APIRouter()

_OPENAI_INCLUDE = ["gpt-5"]
_OPENAI_EXCLUDE = ["realtime", "preview", "audio", "vision"]


@router.get("/config")
async def get_config(request: Request) -> dict:
    cfg = request.app.state.wally.config
    return {
        "bot": asdict(cfg.bot),
        "openai": asdict(cfg.openai),
        "discord": asdict(cfg.discord),
        "twitch": asdict(cfg.twitch),
        "emotions": {k: asdict(v) for k, v in cfg.emotions.items()},
        "twitch_events": {k: asdict(v) for k, v in cfg.twitch_events.items()},
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
        if "secondary_model" in d:
            cfg.openai.secondary_model = str(d["secondary_model"])
        if "max_tokens" in d:
            cfg.openai.max_tokens = int(d["max_tokens"])
        if "reasoning_effort" in d:
            val = str(d["reasoning_effort"])
            if val not in VALID_REASONING_EFFORTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"reasoning_effort must be one of {VALID_REASONING_EFFORTS}",
                )
            cfg.openai.reasoning_effort = val
        if "text_verbosity" in d:
            val = str(d["text_verbosity"])
            if val not in VALID_TEXT_VERBOSITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"text_verbosity must be one of {VALID_TEXT_VERBOSITIES}",
                )
            cfg.openai.text_verbosity = val

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

    if "twitch" in body:
        d = body["twitch"]
        if "guest_channels" in d:
            cfg.twitch.guest_channels = list(d["guest_channels"])  # liste : remplacement intégral
        if "cooldown_seconds" in d:
            cfg.twitch.cooldown_seconds = int(d["cooldown_seconds"])

    if "emotions" in body:
        for name, d in body["emotions"].items():
            if name in cfg.emotions and "decay_lambda" in d:
                lam = float(d["decay_lambda"])
                if lam <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"decay_lambda for {name} must be > 0",
                    )
                cfg.emotions[name].decay_lambda = lam

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
            state.config.openai.primary_model,
            state.config.openai.secondary_model,
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
