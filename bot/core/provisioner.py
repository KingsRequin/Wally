"""Provisioning d'instances Wally isolées."""
from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import yaml
from loguru import logger

INSTANCES_DIR = Path("/opt/stacks/wally-instances")
_WALLY_DIR = Path("/opt/stacks/wally-ai")
_SHARED_IMAGE = "wally-ai-wally"
_SHARED_NETWORK = "wally-ai_wally-net"


async def provision_instance(
    slug: str, port: int, data: dict, dry_run: bool = False
) -> str:
    """Crée le répertoire d'instance, génère les fichiers, lance Docker.

    Returns l'URL de l'instance (ex: http://host:8081).
    dry_run=True génère les fichiers mais ne lance pas Docker.
    """
    slug_dir = INSTANCES_DIR / slug
    _create_directories(slug_dir)
    _write_env(slug_dir, slug, data)
    _write_config_yaml(slug_dir, slug, data)
    _write_persona_files(slug_dir, slug, data)
    _write_docker_compose(slug_dir, slug, port)

    if not dry_run:
        await _run_docker_compose(slug_dir / "docker-compose.yml")
        logger.info("Instance {} started on port {}", slug, port)
    else:
        logger.info("Instance {} dry-run complete (no Docker)", slug)

    return f"http://localhost:{port}"


def _create_directories(slug_dir: Path) -> None:
    for sub in ["data", "logs", "bot/persona"]:
        (slug_dir / sub).mkdir(parents=True, exist_ok=True)


def _write_env(slug_dir: Path, slug: str, data: dict) -> None:
    jwt_secret = secrets.token_hex(32)
    env_content = (
        f"OPENAI_API_KEY={data.get('openai_api_key', '')}\n"
        f"ANTHROPIC_API_KEY={data.get('anthropic_api_key', '')}\n"
        f"TAVILY_API_KEY={data.get('tavily_api_key', '')}\n"
        f"DISCORD_TOKEN={data.get('discord_token', '')}\n"
        f"DISCORD_GUILD_ID={data.get('discord_guild_id', '')}\n"
        f"DISCORD_CLIENT_ID={data.get('discord_client_id', '')}\n"
        f"DISCORD_CLIENT_SECRET={data.get('discord_client_secret', '')}\n"
        f"WEB_BASE_URL={data.get('web_base_url', '')}\n"
        f"JWT_SECRET={jwt_secret}\n"
        f"QDRANT_URL=http://wally-qdrant:6333\n"
        f"QDRANT_COLLECTION_NAME=wally_{slug}\n"
        f"DB_PATH=data/wally.db\n"
        f"COMPOSE_FILE={INSTANCES_DIR / slug}/docker-compose.yml\n"
        f"CLOUDFLARED_WALLY_TOKEN=\n"
    )
    if data.get("twitch_enabled"):
        env_content += (
            f"TWITCH_CLIENT_ID={data.get('twitch_client_id', '')}\n"
            f"TWITCH_CLIENT_SECRET={data.get('twitch_client_secret', '')}\n"
            f"TWITCH_BOT_NICK={data.get('twitch_bot_nick', '')}\n"
            f"TWITCH_BROADCASTER_ID={data.get('twitch_broadcaster_id', '')}\n"
            f"TWITCH_BOT_ID={data.get('twitch_bot_id', '')}\n"
            f"BOT_ACCESS_TOKEN={data.get('bot_access_token', '')}\n"
            f"BOT_REFRESH_TOKEN={data.get('bot_refresh_token', '')}\n"
            f"STREAMER_ACCESS_TOKEN={data.get('streamer_access_token', '')}\n"
            f"STREAMER_REFRESH_TOKEN={data.get('streamer_refresh_token', '')}\n"
        )
    (slug_dir / ".env").write_text(env_content)


def _write_config_yaml(slug_dir: Path, slug: str, data: dict) -> None:
    bot_name = data.get("bot_name", slug)
    lang = data.get("language_default", "fr")
    triggers = data.get("trigger_names") or [bot_name]
    cfg = {
        "bot": {
            "trigger_names": triggers,
            "language_default": lang,
            "context_window_size": 20,
            "context_token_threshold": 3000,
            "journal_time": "21:00",
            "journal_channel_id": None,
            "dashboard_token": secrets.token_hex(16),
            "prelude_window_size": 15,
            "link_min_confidence": 0.75,
            "cost_alert_threshold": 25.0,
            "emotion_inertia_factor": 0.5,
            "emotion_peak_threshold": 0.7,
            "spontaneous_discord_enabled": True,
            "spontaneous_twitch_enabled": bool(data.get("twitch_enabled")),
            "spontaneous_probability": 0.05,
            "spontaneous_passion_probability": 0.15,
            "spontaneous_cooldown_seconds": 300,
            "spontaneous_memory_probability": 0.2,
            "memory_recall_min_score": 0.75,
            "memory_search_min_score": 0.5,
            "memory_context_max_tokens": 800,
            "love_decay_lambda": 0.1,
        },
        "discord": {
            "anger_trigger_threshold": 3,
            "timeout_minutes": 10,
            "channel_filter_mode": "blacklist",
            "channel_blacklist": [],
            "channel_whitelist": [],
            "emoji_reaction_probability": 0.05,
            "spam_detection": {
                "enabled": True,
                "max_messages": 10,
                "window_seconds": 120,
                "mute_minutes": 5,
                "spam_anger_delta": 0.05,
                "exempt_channels": [],
            },
        },
        "llm": {
            "primary": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.8,
                "max_tokens": 1000,
            },
            "secondary": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.8,
                "max_tokens": 500,
            },
        },
        "openai": {
            "primary_model": "gpt-4o-mini",
            "secondary_model": "gpt-4o-mini",
            "temperature": 0.8,
            "max_tokens": 1000,
        },
        "emotions": {
            "anger": {"decay_lambda": 3.0, "boredom_rise_per_hour": None},
            "joy": {"decay_lambda": 1.5, "boredom_rise_per_hour": None},
            "sadness": {"decay_lambda": 1.0, "boredom_rise_per_hour": None},
            "curiosity": {"decay_lambda": 1.5, "boredom_rise_per_hour": None},
            "boredom": {"decay_lambda": 0.01, "boredom_rise_per_hour": 0.2},
            "circadian": {"enabled": False, "timezone": "Europe/Paris", "periods": {}},
            "mood": {"alpha": 0.02, "decay_lambda": 0.1, "bias_factor": 0.3},
            "fatigue": {"dampening": 0.7, "recovery_rate": 0.1},
            "habituation": {
                "threshold_count": 3, "window_seconds": 600,
                "decay_factor": 0.5, "reset_seconds": 1800, "exempt": ["anger"],
            },
            "memory": {
                "learning_rate": 0.05, "priming_factor": 0.05,
                "amplification_factor": 0.3, "decay_lambda_per_day": 0.01,
            },
        },
        "twitch": {"guest_channels": [], "cooldown_seconds": 30},
        "twitch_events": {
            k: {"active": False, "message": ""}
            for k in ("follow", "sub", "resub", "bits", "raid")
        },
        "image_generation": {
            "model": "gpt-image-1", "quality": "medium",
            "size": "1024x1024", "background": "auto",
            "format": "png", "daily_limit": 10, "per_user_limit": 3,
        },
        "overlay_image": {"display_duration": 15, "enabled": True},
        "theme": {
            "accent_color": "#06b6d4",
            "bg_color": "#11151c",
            "surface_color": "rgba(255,255,255,0.03)",
            "sidebar_bg": "rgba(255,255,255,0.02)",
            "layout_variant": "sidebar-left",
            "tab_style": "icons-only",
        },
    }
    (slug_dir / "config.yaml").write_text(yaml.dump(cfg, allow_unicode=True))


def _write_persona_files(slug_dir: Path, slug: str, data: dict) -> None:
    persona_dir = slug_dir / "bot" / "persona"
    staged_dir = _WALLY_DIR / "docs" / f"{slug}-persona"

    def _get(key: str, filename: str) -> str:
        wizard_val = data.get(key, "")
        if wizard_val:
            return wizard_val
        staged_path = staged_dir / filename
        if staged_path.exists():
            return staged_path.read_text()
        return ""

    files = {
        "SOUL.md": _get("persona_soul", "SOUL.md"),
        "IDENTITY.md": _get("persona_identity", "IDENTITY.md"),
        "VOICE.md": _get("persona_voice", "VOICE.md"),
        "EMOTIONS.md": _get("persona_emotions", "EMOTIONS.md"),
        "EXEMPLES.md": _get("persona_exemples", "EXEMPLES.md"),
        "WEEKDAYS.md": _get("persona_weekdays", "WEEKDAYS.md"),
        "COMPOSITES.md": _get("persona_composites", "COMPOSITES.md"),
        "SECONDARIES.md": _get("persona_secondaries", "SECONDARIES.md"),
    }
    if staged_dir.exists():
        logger.info("Instance {}: loading staged persona from {}", slug, staged_dir)
    for filename, content in files.items():
        (persona_dir / filename).write_text(content)


def _get_docker_gid() -> int:
    """Retourne le GID du socket Docker (pour group_add dans les instances)."""
    try:
        return os.stat("/var/run/docker.sock").st_gid
    except Exception:
        return 996  # valeur par défaut sur ce host


def _write_docker_compose(slug_dir: Path, slug: str, port: int) -> None:
    compose_path = slug_dir / "docker-compose.yml"
    docker_gid = _get_docker_gid()
    compose = {
        "networks": {_SHARED_NETWORK: {"external": True}},
        "services": {
            slug: {
                "image": _SHARED_IMAGE,
                "container_name": f"wally-{slug}",
                "user": "1000:1000",
                "group_add": [str(docker_gid)],
                "networks": [_SHARED_NETWORK],
                "env_file": ".env",
                "ports": [f"0.0.0.0:{port}:8080"],
                "volumes": [
                    "./data:/app/data",
                    "./logs:/app/logs",
                    "./config.yaml:/app/config.yaml",
                    "./.env:/app/.env",
                    "./bot/persona:/app/bot/persona",
                    f"{_WALLY_DIR}/bot/persona/prompts:/app/bot/persona/prompts:ro",
                    "/var/run/docker.sock:/var/run/docker.sock",
                    "/usr/bin/docker:/usr/bin/docker:ro",
                    "/usr/libexec/docker/cli-plugins/docker-compose:/usr/libexec/docker/cli-plugins/docker-compose:ro",
                    "./docker-compose.yml:/app/docker-compose.yml:ro",
                ],
                "restart": "unless-stopped",
            }
        },
    }
    compose_path.write_text(yaml.dump(compose, allow_unicode=True))


async def _run_docker_compose(compose_path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/docker", "compose", "-f", str(compose_path), "up", "-d",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"docker compose up timed out after 60s for {compose_path.parent.name}")
    if proc.returncode != 0:
        raise RuntimeError(f"docker compose up failed: {stderr.decode()}")
    logger.info("docker compose up: {}", stdout.decode().strip())
