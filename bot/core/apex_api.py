# bot/core/apex_api.py
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    pass

_BASE_URL = "https://api.mozambiquehe.re"

APEX_LEGENDS_TOOL = {
    "type": "function",
    "function": {
        "name": "apex_legends",
        "description": (
            "Retrieve Apex Legends game data. Use ONLY when the user asks "
            "about Apex Legends specifically. "
            "\n"
            "ACTIONS: "
            "player_stats → player rank, level, legend, kills. Requires 'player_name' "
            "and 'platform' (PC, PS4, X1). DEFAULT platform to PC if not specified. "
            "map_rotation → current and next maps for BR, Arenas, Control. "
            "crafting → items currently in replicators. "
            "news → latest Apex Legends news and patch notes. "
            "predator → current RP/AP threshold to reach Apex Predator. "
            "server_status → check if Apex servers are online. "
            "\n"
            "DECISION TEST: Is the user asking a specific question about "
            "Apex Legends game state or player data? "
            "YES → use this tool. NO → do NOT use. "
            "\n"
            "USE: 'c'est quoi le rank de Daltoosh?' → player_stats "
            "USE: 'quelle map en ce moment sur Apex?' → map_rotation "
            "USE: 'c'est quoi le craft du jour?' → crafting "
            "USE: 'les serveurs Apex marchent?' → server_status "
            "USE: 'il faut combien de points pour pred?' → predator "
            "NO USE: 'Apex c'est nul' → opinion, not a data request "
            "NO USE: 'tu joues à Apex?' → casual question about the bot"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "player_stats",
                        "map_rotation",
                        "crafting",
                        "news",
                        "predator",
                        "server_status",
                    ],
                    "description": "Which data to retrieve",
                },
                "player_name": {
                    "type": "string",
                    "description": "Player username (required for player_stats)",
                },
                "platform": {
                    "type": "string",
                    "enum": ["PC", "PS4", "X1"],
                    "description": "Platform (default PC, only for player_stats)",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


class ApexLegendsService:
    def __init__(self):
        self._api_key = os.environ.get("APEX_API_KEY", "")
        self._lock = asyncio.Lock()
        self._last_request: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def _rate_limit(self) -> None:
        """Enforce max 2 requests/second (0.5s between calls)."""
        async with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < 0.5:
                await asyncio.sleep(0.5 - elapsed)
            self._last_request = time.monotonic()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict | list | str:
        await self._rate_limit()
        url = f"{_BASE_URL}/{endpoint}"
        headers = {"Authorization": self._api_key}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers, params=params or {})
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Apex API {endpoint} HTTP {code}", endpoint=endpoint, code=exc.response.status_code)
            return f"Apex API error (HTTP {exc.response.status_code})"
        except Exception as exc:
            logger.error("Apex API {endpoint} error: {e}", endpoint=endpoint, e=exc)
            return f"Apex API error: {exc}"

    async def execute(self, action: str, player_name: str = "", platform: str = "PC") -> str:
        """Route to the correct endpoint and return formatted results."""
        if action == "player_stats":
            return await self._player_stats(player_name, platform)
        elif action == "map_rotation":
            return await self._map_rotation()
        elif action == "crafting":
            return await self._crafting()
        elif action == "news":
            return await self._news()
        elif action == "predator":
            return await self._predator()
        elif action == "server_status":
            return await self._server_status()
        return f"Unknown action: {action}"

    async def _player_stats(self, player_name: str, platform: str) -> str:
        if not player_name:
            return "Player name is required for player_stats."
        data = await self._get("bridge", {"player": player_name, "platform": platform})
        if isinstance(data, str):
            return data
        return self._format_player(data)

    async def _map_rotation(self) -> str:
        data = await self._get("maprotation", {"version": "2"})
        if isinstance(data, str):
            return data
        return self._format_maps(data)

    async def _crafting(self) -> str:
        data = await self._get("crafting")
        if isinstance(data, str):
            return data
        return self._format_crafting(data)

    async def _news(self) -> str:
        data = await self._get("news", {"lang": "fr-FR"})
        if isinstance(data, str):
            return data
        return self._format_news(data)

    async def _predator(self) -> str:
        data = await self._get("predator")
        if isinstance(data, str):
            return data
        return self._format_predator(data)

    async def _server_status(self) -> str:
        data = await self._get("servers")
        if isinstance(data, str):
            return data
        return self._format_servers(data)

    # ── Formatters ────────────────────────────────────────────────────────────

    def _format_player(self, data: dict) -> str:
        parts = []
        g = data.get("global", {})
        parts.append(f"Player: {g.get('name', '?')} (Level {g.get('level', '?')})")
        parts.append(f"Platform: {g.get('platform', '?')}")

        rank = g.get("rank", {})
        if rank:
            parts.append(
                f"BR Rank: {rank.get('rankName', '?')} {rank.get('rankDiv', '')} "
                f"({rank.get('rankScore', 0)} RP)"
            )

        arena_rank = g.get("arena", {})
        if arena_rank and arena_rank.get("rankName"):
            parts.append(
                f"Arena Rank: {arena_rank.get('rankName', '?')} {arena_rank.get('rankDiv', '')} "
                f"({arena_rank.get('rankScore', 0)} AP)"
            )

        bans = g.get("bpisBanned") or g.get("bans", {})
        if isinstance(bans, dict) and bans.get("isActive"):
            parts.append("⚠️ BANNED")

        selected = data.get("legends", {}).get("selected", {})
        if selected:
            parts.append(f"Selected Legend: {selected.get('LegendName', '?')}")
            trackers = selected.get("data", [])
            for t in trackers[:3]:
                parts.append(f"  - {t.get('name', '?')}: {t.get('value', '?')}")

        return "\n".join(parts)

    def _format_maps(self, data: dict) -> str:
        parts = []
        for mode_key, mode_name in [
            ("battle_royale", "Battle Royale"),
            ("ranked", "Ranked"),
            ("ltm", "LTM"),
        ]:
            mode = data.get(mode_key)
            if not mode:
                continue
            current = mode.get("current", {})
            nxt = mode.get("next", {})
            remaining = current.get("remainingTimer", "?")
            parts.append(
                f"{mode_name}: {current.get('map', '?')} "
                f"(encore {remaining}) → prochain: {nxt.get('map', '?')}"
            )
        return "\n".join(parts) if parts else "No map rotation data."

    def _format_crafting(self, data: list | dict) -> str:
        if not isinstance(data, list):
            return str(data)
        parts = []
        for bundle in data:
            bundle_type = bundle.get("bundleType", "?")
            items = bundle.get("bundleContent", [])
            item_names = [i.get("itemType", {}).get("name", "?") for i in items]
            parts.append(f"{bundle_type}: {', '.join(item_names)}")
        return "\n".join(parts) if parts else "No crafting data."

    def _format_news(self, data: list | dict) -> str:
        if isinstance(data, dict):
            data = data.get("news", data.get("items", []))
        if not isinstance(data, list):
            return str(data)
        parts = []
        for article in data[:5]:
            title = article.get("title", "?")
            link = article.get("link", "")
            short = article.get("short_desc", "")
            parts.append(f"- {title}: {short}" + (f" ({link})" if link else ""))
        return "\n".join(parts) if parts else "No news."

    def _format_predator(self, data: dict) -> str:
        parts = []
        for platform_key, label in [("PC", "PC"), ("PS4", "PS4"), ("X1", "Xbox")]:
            rp = data.get("RP", {}).get(platform_key, {})
            ap = data.get("AP", {}).get(platform_key, {})
            if rp:
                parts.append(
                    f"{label} BR: Top {rp.get('totalMastersAndPreds', '?')} — "
                    f"seuil Pred: {rp.get('val', '?')} RP"
                )
            if ap:
                parts.append(
                    f"{label} Arena: Top {ap.get('totalMastersAndPreds', '?')} — "
                    f"seuil Pred: {ap.get('val', '?')} AP"
                )
        return "\n".join(parts) if parts else "No predator data."

    def _format_servers(self, data: dict) -> str:
        parts = []
        for region_group in data.values():
            if not isinstance(region_group, dict):
                continue
            for name, info in region_group.items():
                if isinstance(info, dict) and info.get("Status"):
                    status = info["Status"]
                    emoji = "✅" if status == "UP" else "❌"
                    parts.append(f"{emoji} {name}: {status}")
        return "\n".join(parts[:10]) if parts else "No server data."

    def get_tool_definition(self) -> dict:
        return APEX_LEGENDS_TOOL
