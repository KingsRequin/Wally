# bot/dashboard/routes/config_discord.py
"""Réglages Discord du panel admin (Serveur communautaire, salons, anti-spam).

Le catalogue sert tous les sélecteurs de salon du panel (`formulaires.js`) :
ids en CHAÎNES, jamais en nombres — un snowflake dépasse 2^53 et `JSON.parse`
l'arrondit en silence.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

admin_router = APIRouter()


@admin_router.get("/discord/catalogue")
async def catalogue(request: Request) -> dict:
    """Serveurs, salons textuels et vocaux, catégories et rôles que Wally voit."""
    bot = request.app.state.wally.discord_bot
    if bot is None:
        return {"guilds": []}
    guilds = []
    for g in bot.guilds:
        guilds.append({
            "id": str(g.id),
            "name": g.name,
            "text_channels": [{"id": str(c.id), "name": c.name} for c in g.text_channels],
            "voice_channels": [{"id": str(c.id), "name": c.name} for c in g.voice_channels],
            "categories": [{"id": str(c.id), "name": c.name} for c in g.categories],
            "roles": [{"id": str(r.id), "name": r.name} for r in g.roles
                      if not r.is_default()],
        })
    return {"guilds": guilds}
