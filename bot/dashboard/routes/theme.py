# bot/dashboard/routes/theme.py
"""Routes de theming : CSS dynamique + API admin."""
from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from bot.config import ThemeConfig, VALID_LAYOUT_VARIANTS, VALID_TAB_STYLES

# Router pour l'API admin /api/admin/theme
router = APIRouter()

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGBA_RE = re.compile(r"^rgba?\([\d\s,./]+\)$")


def _hex_to_rgba_soft(hex_color: str, alpha: float = 0.12) -> str:
    """Convertit #rrggbb → rgba(r, g, b, alpha). Retourne le défaut cyan si invalide."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except Exception:
        return f"rgba(6, 182, 212, {alpha})"


def _is_valid_color(value: str) -> bool:
    return bool(_HEX_RE.match(value) or _RGBA_RE.match(value))


def generate_theme_css(theme: ThemeConfig) -> str:
    """Génère le contenu CSS des variables de thème."""
    accent_soft = _hex_to_rgba_soft(theme.accent_color)
    return f""":root {{
  --accent: {theme.accent_color};
  --accent-soft: {accent_soft};
  --bg-body: {theme.bg_color};
  --bg-surface: {theme.surface_color};
  --bg-sidebar: {theme.sidebar_bg};
  --layout-variant: "{theme.layout_variant}";
  --tab-style: "{theme.tab_style}";
}}
"""


async def serve_theme_css(request: Request) -> Response:
    """Endpoint GET /static/theme.css — CSS dynamique depuis config.theme."""
    theme = request.app.state.wally.config.theme
    css = generate_theme_css(theme)
    return Response(
        content=css,
        media_type="text/css",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "CDN-Cache-Control": "no-store",
        },
    )


@router.get("/theme")
async def get_theme(request: Request) -> dict:
    """Retourne la config de thème courante."""
    return asdict(request.app.state.wally.config.theme)


@router.post("/theme")
async def update_theme(request: Request, body: dict) -> dict:
    """Met à jour la config de thème et sauvegarde."""
    cfg = request.app.state.wally.config
    theme = cfg.theme
    color_fields = {"accent_color", "bg_color", "surface_color", "sidebar_bg"}
    for field, value in body.items():
        if field in color_fields:
            if not _is_valid_color(str(value)):
                raise HTTPException(status_code=400, detail=f"{field}: couleur invalide (hex #rrggbb ou rgba(...))")
            setattr(theme, field, value)
        elif field == "layout_variant":
            if value not in VALID_LAYOUT_VARIANTS:
                raise HTTPException(status_code=400, detail=f"layout_variant invalide: {value}")
            theme.layout_variant = value
        elif field == "tab_style":
            if value not in VALID_TAB_STYLES:
                raise HTTPException(status_code=400, detail=f"tab_style invalide: {value}")
            theme.tab_style = value
    cfg.save()
    return asdict(theme)
