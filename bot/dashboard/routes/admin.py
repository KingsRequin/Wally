# bot/dashboard/routes/admin.py
from __future__ import annotations

import copy
import asyncio
import os
import re
from dataclasses import asdict
from pathlib import Path

# Strong refs for fire-and-forget tasks (prevents GC cancellation)
_bg_tasks: set[asyncio.Task] = set()

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.config import VALID_REASONING_EFFORTS, VALID_TEXT_VERBOSITIES, VALID_THINKING_TYPES, VALID_THINKING_EFFORTS
from bot.core.llm import SUPPORTED_TEXT_PROVIDERS
from bot.core.overlay_feed import payload_image_galerie

router = APIRouter()

_OPENAI_INCLUDE = ["gpt", "chatgpt", "o1", "o3", "o4"]
_OPENAI_EXCLUDE = ["realtime", "preview", "audio", "vision"]
# Un login Twitch : minuscules, chiffres, tirets bas, 25 max.
_TWITCH_LOGIN_RE = re.compile(r'^[a-z0-9_]{1,25}$')


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
        "voice": asdict(cfg.voice),
        # Ce que la factory sait réellement construire. Le `<select>` du
        # dashboard listait « OpenAI » et « Claude » en dur, aucun des deux
        # constructible : le provider en cours (`deepseek`) n'y figurant pas, le
        # navigateur affichait « OpenAI » comme sélectionné et la première
        # sauvegarde cassait la config. La liste vient maintenant du serveur.
        "llm_providers": list(SUPPORTED_TEXT_PROVIDERS),
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
    # Instantané AVANT toute mutation. La fonction écrit dans `cfg` — et dans les
    # clients LLM vivants — au fil de la lecture du body, mais n'appelle
    # `cfg.save()` qu'à la toute fin : une validation qui échoue plus loin
    # (`reasoning_effort`, `thinking_budget_tokens`, `max_messages`, `quality`…)
    # laissait derrière elle les mutations déjà faites. Le bot tournait alors
    # avec des réglages absents de `config.yaml`, sans trace, et un
    # `config.save()` déclenché ailleurs les gravait — pendant que l'appelant,
    # ayant reçu un 400, croyait que rien n'avait été appliqué.
    _avant = copy.deepcopy(cfg)

    try:
        return await _appliquer_config(request, body, state, cfg)
    except HTTPException:
        # On rend la config telle qu'elle était, y compris aux clients vivants.
        state.config = _avant
        _restaurer_clients_llm(state, _avant)
        raise


async def _appliquer_config(request: Request, body: dict, state, cfg) -> dict:
    if "openai" in body:
        d = body["openai"]
        if "temperature" in d:
            temp = float(d["temperature"])
            if not (0.0 <= temp <= 2.0):
                raise HTTPException(status_code=400, detail="temperature must be 0.0–2.0")
            cfg.openai.temperature = temp
            # Propagée vers `llm:`, comme tous les autres champs de la section
            # héritée. Elle était le SEUL à ne pas l'être, alors que
            # `_build_llm_config` privilégie `llm:` dès qu'elle existe et n'y
            # retombe jamais sur `openai:` : la température réglée au dashboard
            # n'était appliquée ni à chaud ni au redémarrage.
            cfg.llm.primary.temperature = temp
            cfg.llm.secondary.temperature = temp
            for client in (state.primary_llm, state.secondary_llm):
                if hasattr(client, "temperature"):
                    client.temperature = temp
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
        # Refuser AVANT de toucher à quoi que ce soit. La mutation venait en
        # premier et la construction du client ensuite : un provider inconnu
        # levait une `ValueError` non attrapée (HTTP 500) en laissant
        # `cfg.llm.*` corrompu en mémoire. Le `config.save()` suivant — un autre
        # onglet, `/wally setup` — gravait alors ce provider dans `config.yaml`,
        # et le bot mourait au démarrage suivant, en boucle de restart Docker.
        for role in ("primary", "secondary"):
            demande = (llm_data.get(role) or {}).get("provider")
            if demande is not None and demande not in SUPPORTED_TEXT_PROVIDERS:
                raise HTTPException(
                    status_code=400,
                    detail=(f"provider {demande!r} inconnu — "
                            f"supportés : {', '.join(SUPPORTED_TEXT_PROVIDERS)}"),
                )

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
            # `str(None)` vaut « None », une chaîne NON VIDE : le `or None`
            # ne s'appliquait jamais, et un `null` en JSON transformait le jeton
            # admin en la chaîne devinable « None » — que `config.save()`
            # gravait, et que `compare_digest` acceptait ensuite.
            _brut = d["dashboard_token"]
            cfg.bot.dashboard_token = str(_brut).strip() if _brut else None
        if "trigger_names" in d:
            cfg.bot.trigger_names = list(d["trigger_names"])  # liste : remplacement intégral
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
        if "ignored_users" in d:
            # Normalisé À L'ENREGISTREMENT : le filtre compare en minuscules, et
            # une saisie « WZBot » stockée telle quelle donnerait une liste que
            # l'utilisateur relit sans comprendre pourquoi elle diffère. Les
            # doublons et les lignes vides partent au passage.
            #
            # VALIDÉ comme un login Twitch : cette liste est réaffichée dans le
            # dashboard, une saisie libre y ferait entrer du balisage.
            vus: list[str] = []
            for nom in d["ignored_users"]:
                nom = str(nom).strip().lstrip("@").lower()
                if not nom:
                    continue
                if not _TWITCH_LOGIN_RE.match(nom):
                    raise HTTPException(
                        400, f"pseudo Twitch invalide : {nom[:32]!r}"
                    )
                if nom not in vus:
                    vus.append(nom)
            cfg.twitch.ignored_users = vus

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

    # Voice config
    if "voice" in body:
        d = body["voice"]
        v = cfg.voice
        if "enabled" in d:
            v.enabled = bool(d["enabled"])
        if "azure_voice" in d:
            v.azure_voice = str(d["azure_voice"])
        if "language" in d:
            v.language = str(d["language"])
        if "auto_leave_minutes" in d:
            val = int(d["auto_leave_minutes"])
            if not (1 <= val <= 60):
                raise HTTPException(400, "auto_leave_minutes must be 1-60")
            v.auto_leave_minutes = val
        if "vad_aggressiveness" in d:
            val = int(d["vad_aggressiveness"])
            if not (0 <= val <= 3):
                raise HTTPException(400, "vad_aggressiveness must be 0-3")
            v.vad_aggressiveness = val
        # Hot-reload de la voix/seuils si le service vocal tourne (sinon pris au prochain boot).
        vs = getattr(request.app.state.wally, "voice_service", None)
        if vs is not None:
            vs.reload_config(cfg.voice)

    cfg.save()
    return {"status": "saved"}


def _restaurer_clients_llm(state, cfg) -> None:
    """Remet la température d'origine sur les clients LLM déjà mutés."""
    for attribut, role in (("llm", "primary"), ("llm_secondary", "secondary")):
        client = getattr(state, attribut, None)
        if client is None:
            continue
        try:
            client.temperature = getattr(cfg.llm, role).temperature
        except Exception:  # noqa: BLE001 — la restauration ne doit jamais lever
            pass


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
        logger.warning("Failed to list OpenAI models: {e!r}", e=exc)
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
        logger.warning("Failed to list Claude models: {e!r}", e=exc)
        return {"models": [
            state.config.llm.primary.model,
            state.config.llm.secondary.model,
        ]}



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
    """Liste les connexions récentes au chat web (avec flag `banned`)."""
    state = request.app.state.wally
    limit = max(1, min(limit, 200))
    connections = await state.db.list_chat_connections(limit)
    banned_ids = {b["discord_id"] for b in await state.db.list_chat_bans()}
    for c in connections:
        c["banned"] = str(c["discord_id"]) in banned_ids
    return {"connections": connections}


@router.get("/chat-connections/{discord_id}/messages")
async def user_chat_messages(request: Request, discord_id: str, limit: int = 100) -> dict:
    """Messages web envoyés par un utilisateur donné (plus récents d'abord)."""
    state = request.app.state.wally
    limit = max(1, min(limit, 500))
    messages = await state.db.load_chat_messages_for_user(discord_id, limit)
    return {"messages": messages}


@router.get("/ignored")
async def list_ignored(request: Request) -> dict:
    """Tout ce que Wally ignore, réglable ou non, en un seul appel.

    Trois mécanismes coexistent et ne se voyaient nulle part ensemble : la
    liste Twitch de la config, la table des bannis Discord, et deux socles
    câblés en dur. Le panneau les montre côte à côte parce que la question
    qu'on se pose est « pourquoi Wally lit-il encore ce compte ? » — et la
    réponse est dans celui des trois qu'on n'avait pas sous les yeux.

    Le SOCLE est servi ici, jamais recopié dans le JavaScript. Une liste
    dupliquée au front diverge du jour où quelqu'un ajoute un bot à
    `handlers._KNOWN_BOTS`, et le panneau annonce alors le contraire du code
    qui décide. C'est la règle que le panneau de mise en scène a déjà payée.

    Lecture seule : les écritures gardent leurs routes (`/chat-bans` pour
    Discord, `/config` pour Twitch), qui portent déjà leur validation.
    """
    from bot.twitch.handlers import _KNOWN_BOTS

    state = request.app.state.wally
    bans = await state.db.list_chat_bans()
    return {
        "discord": [
            {
                # Sans pseudo, l'id : la table ne l'exige pas, et une carte
                # vide ne dirait plus qui on a ignoré.
                "id": str(b.get("discord_id") or ""),
                "label": b.get("username") or str(b.get("discord_id") or ""),
                "reason": b.get("reason"),
                "depuis": b.get("banned_at"),
            }
            for b in bans or []
        ],
        # `or []` et pas un défaut de `.get` : un `config.yaml` antérieur peut
        # porter `ignored_users: null`, que le défaut ne couvre PAS.
        "twitch": list(getattr(state.config.twitch, "ignored_users", None) or []),
        "socle": {
            "discord": "Tous les bots Discord sont ignorés d'office "
                       "(Wally ne lit jamais un message dont l'auteur est un bot).",
            "twitch": sorted(_KNOWN_BOTS),
            "twitch_badge": "Les comptes portant le badge « bot » sur Twitch "
                            "le sont également, sans être listés ici.",
        },
    }


@router.get("/chat-bans")
async def list_chat_bans(request: Request) -> dict:
    """Liste les utilisateurs bannis du chat/bot."""
    state = request.app.state.wally
    return {"bans": await state.db.list_chat_bans()}


@router.post("/chat-bans")
async def ban_chat_user(request: Request) -> dict:
    """Bannit un utilisateur (par discord_id). Wally l'ignore partout."""
    body = await request.json()
    discord_id = str(body.get("discord_id", "")).strip()
    if not discord_id:
        raise HTTPException(400, detail="discord_id requis")
    state = request.app.state.wally
    username = body.get("username")
    reason = body.get("reason")
    await state.db.ban_chat_user(discord_id, username, reason)
    logger.info("Chat user banned: {u} ({id})", u=username, id=discord_id)
    return {"status": "banned", "discord_id": discord_id}


@router.delete("/chat-bans/{discord_id}")
async def unban_chat_user(request: Request, discord_id: str) -> dict:
    """Lève le bannissement d'un utilisateur."""
    state = request.app.state.wally
    await state.db.unban_chat_user(discord_id)
    logger.info("Chat user unbanned: {id}", id=discord_id)
    return {"status": "unbanned", "discord_id": discord_id}


@router.post("/overlay-image/test")
async def test_overlay_image(request: Request):
    state = request.app.state.wally
    image = await state.db.get_random_gallery_image(state.config.overlay_image.random_filter)
    if not image:
        raise HTTPException(404, "No images in gallery to test")
    # Sans `scene` : ce bouton-ci teste les RÉGLAGES d'image (durée, animation),
    # il vise donc toutes les pages, comme un vrai `!image`. Le ▶ de la mise en
    # scène, lui, cible une seule scène.
    payload = payload_image_galerie(image, state.config.overlay_image)
    # Plus besoin de vider quoi que ce soit : chaque overlay connecté a sa
    # propre file, et la page remplace l'image affichée à la réception.
    state.overlay_image_feed.publish(payload)
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
        "update_available": (
            state.update_checker.update_available
            if state.update_checker is not None
            else False
        ),
        "git_hash": os.getenv("BOT_GIT_HASH", "unknown"),
        "build_date": os.getenv("BOT_BUILD_DATE", "unknown"),
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

    # Liste EN DUR, et c'est voulu : elle définit ce qui est éditable, là où un glob
    # exposerait aussi les fichiers de travail du dossier. Mais elle avait cessé de
    # suivre — CAPABILITIES.md (le self-model, lu à chaque réponse), EVENTS.md (le ton
    # par type d'événement d'overlay) et USERS.md (les clés utilisateurs) sont tous
    # actifs en production et n'apparaissaient pas dans l'onglet Prompts. Le POST les
    # acceptait déjà (`^[A-Z_]+\.md$`) : seule la lecture les ignorait.
    persona_files = ["SOUL.md", "IDENTITY.md", "VOICE.md", "EXEMPLES.md",
                     "EMOTIONS.md", "WEEKDAYS.md", "SECONDARIES.md", "COMPOSITES.md",
                     "CAPABILITIES.md", "EVENTS.md", "USERS.md", "FIL.md",
                     "ATTENTE.md"]
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
    if not re.fullmatch(r'[A-Z_]+\.md', filename):
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
    if not re.fullmatch(r'[\w_-]+\.md', filename):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    body = await request.json()
    content = body.get("content", "")
    prompts_dir = Path(__file__).parents[3] / "bot" / "persona" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / filename).write_text(content)
    return {"ok": True}


@router.post("/bot/restart")
async def restart_container(request: Request) -> dict:
    """Redémarre le container via le pont hôte (`wally-bridge.service`).

    Un `docker compose restart` local est structurellement impossible depuis
    l'intérieur du container : ni le binaire `docker`, ni `docker-compose.yml`,
    ni le socket Docker n'y sont montés — d'où l'échec
    `open /app/docker-compose.yml: no such file or directory` vu en prod. Le
    pont hôte (`bot/intelligence/host_bridge.py`) tourne côté hôte et expose
    `docker_restart`, déjà utilisé par `SelfUpgrade`.

    `docker-restart` côté daemon (`scripts/host_bridge_daemon.py`) ne fait que
    DISPATCHER la commande (`subprocess.Popen(..., start_new_session=True)`)
    avant de répondre 200 — la commande `docker compose up -d --force-recreate`
    tourne ensuite de façon détachée sur l'hôte. La réponse HTTP de cette route
    part donc bien avant que ce container ne reçoive son SIGTERM.
    """
    logger.warning("Container restart requested via dashboard")
    from bot.intelligence.host_bridge import bridge_from_env

    bridge = bridge_from_env()
    if bridge is None:
        logger.error("Container restart: pont hôte non configuré (BRIDGE_SECRET absent)")
        raise HTTPException(
            status_code=503,
            detail="Pont hôte non configuré (BRIDGE_SECRET absent) — redémarrage impossible depuis le container.",
        )
    if not await bridge.health():
        logger.error("Container restart: pont hôte injoignable")
        raise HTTPException(
            status_code=503,
            detail="Pont hôte injoignable — le service wally-bridge est-il actif sur l'hôte ?",
        )

    service_name = os.getenv("COMPOSE_PROJECT_NAME", "wally")
    try:
        await bridge.docker_restart(service_name)
    except Exception as e:  # noqa: BLE001 — le résultat réel doit remonter à l'appelant
        logger.error("Container restart failed: {!r}", e)
        raise HTTPException(status_code=503, detail=f"Échec du déclenchement du redémarrage : {e}")

    logger.info("Container restart dispatched via host bridge")
    return {"ok": True, "message": "Redémarrage déclenché via le pont hôte."}


# ── Persistent notes ─────────────────────────────────────────────────────────

@router.get("/notes")
async def get_notes(request: Request) -> dict:
    db = request.app.state.wally.db
    notes = await db.get_persistent_notes()
    return {"notes": notes}


@router.put("/notes/{note_id}")
async def update_note(note_id: int, request: Request) -> dict:
    """Modifie la note d'id `note_id`, titre compris.

    Elle appelait `upsert_persistent_note(title, content)`, dont la clé de
    conflit est `ON CONFLICT(title)` : `note_id` n'était JAMAIS utilisé, et la
    route était rigoureusement identique au POST. Renommer une note créait donc
    un DOUBLON, et l'originale restait injectée dans chaque conversation via
    `_NOTE_TOOLS`. Un `PUT /{id}` qui n'utilise pas son `{id}` est un contrat
    mensonger ; le front ne s'en sortait qu'en relisant le titre depuis le DOM.
    """
    body = await request.json()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or not content:
        raise HTTPException(status_code=400, detail="title et content requis")
    db = request.app.state.wally.db
    if not await db.update_persistent_note(note_id, title, content):
        raise HTTPException(status_code=404, detail="Note introuvable")
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


# ── Aliases ──────────────────────────────────────────────────────────────────

@router.get("/aliases")
async def list_aliases(request: Request, canonical_uid: str | None = None):
    state = request.app.state.wally
    return await state.db.list_aliases(canonical_uid=canonical_uid)


@router.post("/aliases")
async def create_alias(request: Request):
    state = request.app.state.wally
    body = await request.json()
    nickname = (body.get("nickname") or "").strip()
    canonical_uid = (body.get("canonical_uid") or "").strip()
    if not nickname or not canonical_uid:
        raise HTTPException(status_code=400, detail="nickname and canonical_uid are required")
    display_name = body.get("display_name")
    await state.db.upsert_alias(nickname, canonical_uid, display_name=display_name, source="manual", confidence=1.0)
    await state.memory.load_aliases(state.db)
    return {"ok": True}


@router.delete("/aliases/{nickname}")
async def delete_alias(request: Request, nickname: str):
    state = request.app.state.wally
    await state.db.delete_alias(nickname)
    await state.memory.load_aliases(state.db)
    return {"ok": True}


@router.post("/self-update")
async def self_update(request: Request) -> dict:
    """Déclenche la mise à jour de ce container : pull puis recreate via Docker Compose.

    Requiert COMPOSE_FILE dans l'environnement et /var/run/docker.sock monté.
    Lance la commande en arrière-plan pour que la réponse HTTP parte avant l'arrêt du container.
    """
    compose_file = os.getenv("COMPOSE_FILE", "")
    if not compose_file:
        raise HTTPException(status_code=503, detail="COMPOSE_FILE non configuré")
    if not Path("/var/run/docker.sock").exists():
        raise HTTPException(status_code=503, detail="Docker socket non disponible")

    state = request.app.state.wally
    if state.update_checker is not None:
        state.update_checker.update_available = False  # reset optimiste

    cmd = (
        f"/usr/bin/docker compose -f {compose_file} pull && "
        f"/usr/bin/docker compose -f {compose_file} up -d --force-recreate"
    )
    async def _lancer() -> None:
        # `create_subprocess_shell` et non `subprocess.Popen` : le `fork()` d'un
        # process Python à gros tas duplique l'espace d'adressage et GÈLE toute
        # la boucle le temps de l'opération — Discord, Twitch, dashboard, ticks
        # cognitifs compris. `restart_container` (juste au-dessus) est passé par
        # le pont hôte depuis, mais le principe (jamais de fork lourd dans la
        # boucle asyncio) vaut toujours ici, où le socket Docker est monté.
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        await proc.wait()

    task = asyncio.create_task(_lancer())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    logger.info("Self-update triggered (pull + recreate) for COMPOSE_FILE={}", compose_file)
    return {"ok": True}
