# bot/core/apex/service.py
"""Les actions Apex offertes au LLM, rendues en texte lisible.

Le service ne décide de rien : il va chercher, met en forme, et dit clairement
quand il n'a pas. Ce qu'il ne sait pas faire est annoncé dans la description de
l'outil, pour que le modèle n'aille pas le chercher ailleurs.
"""
from __future__ import annotations

import os

from bot.core.apex.client import ApexClient
from bot.core.apex.reader import PlayerProfile, read_profile


def _fr(n: int) -> str:
    """12345 → « 12 345 », lisible dans un chat."""
    return f"{n:,}".replace(",", " ")


class ApexLegendsService:
    # Les libellés des modes, dans l'ordre d'intérêt. `wildcard` manquait :
    # c'est un mode qui tourne, et son absence donnait une rotation incomplète.
    _MODES = (
        ("battle_royale", "Battle Royale"),
        ("ranked", "Ranked"),
        ("ltm", "Mode temporaire"),
        ("wildcard", "Wildcard"),
    )

    def __init__(self, client: ApexClient | None = None) -> None:
        self._client = client or ApexClient(os.environ.get("APEX_API_KEY", ""))

    @property
    def available(self) -> bool:
        return bool(self._client.available)

    def get_tool_definition(self) -> dict:
        from bot.core.apex.tool import APEX_LEGENDS_TOOL
        return APEX_LEGENDS_TOOL

    async def execute(self, action: str, player_name: str = "", platform: str = "PC") -> str:
        if action == "player_stats":
            return await self._player_stats(player_name, platform)
        if action == "map_rotation":
            return await self._map_rotation()
        if action == "crafting":
            return await self._crafting()
        if action == "predator":
            return await self._predator()
        if action == "server_status":
            return await self._server_status()
        return f"Action inconnue : {action}"

    # ── Le profil d'un joueur ─────────────────────────────────────────────────

    async def _player_stats(self, player_name: str, platform: str) -> str:
        if not player_name:
            return "Il me faut un pseudo Apex pour chercher."
        data = await self._client.get(
            "bridge", {"player": player_name, "platform": platform or "PC"}
        )
        if isinstance(data, str):
            return data
        profil = read_profile(data)
        if profil is None:
            erreur = data.get("Error") if isinstance(data, dict) else ""
            return f"{player_name} : pas trouvé sur l'API Apex ({erreur or 'compte inconnu'})."
        return self._render_profile(profil)

    def _render_profile(self, p: PlayerProfile) -> str:
        lignes = [f"{p.name} — niveau {_fr(p.level)} ({p.platform})"]
        if p.rank:
            rang = f"Rang BR : {p.rank.name}"
            if p.rank.div:
                rang += f" {p.rank.div}"
            rang += f" ({_fr(p.rank.score)} RP)"
            if p.rank.top_percent is not None:
                rang += f" — top {p.rank.top_percent} % du ladder"
            lignes.append(rang)
        etat = p.state or "état inconnu"
        if p.legend:
            etat += f", sur {p.legend}"
        lignes.append(f"État : {etat}")
        if p.banned:
            lignes.append(f"⚠️ Banni ({p.ban_reason or 'raison inconnue'})")
        for stat in p.stats.values():
            ligne = f"{stat.label} : {_fr(stat.value)}"
            if stat.top_percent is not None:
                ligne += f" (top {stat.top_percent} % mondial"
                if stat.world_pos is not None:
                    ligne += f", {_fr(stat.world_pos)}ᵉ"
                ligne += ")"
            lignes.append(ligne)
        return "\n".join(lignes)

    # ── L'état du jeu ─────────────────────────────────────────────────────────

    async def _map_rotation(self) -> str:
        data = await self._client.get("maprotation", {"version": "2"})
        if isinstance(data, str):
            return data
        lignes = []
        for cle, nom in self._MODES:
            mode = data.get(cle)
            if not isinstance(mode, dict):
                continue
            courant = mode.get("current") or {}
            suivant = mode.get("next") or {}
            ligne = f"{nom} : {courant.get('map', '?')}"
            if courant.get("remainingTimer"):
                ligne += f" (encore {courant['remainingTimer']})"
            if suivant.get("map"):
                ligne += f" → puis {suivant['map']}"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de rotation disponible."

    async def _crafting(self) -> str:
        data = await self._client.get("crafting")
        if isinstance(data, str):
            return data
        if not isinstance(data, list):
            return "Pas de données de craft."
        lignes = []
        for lot in data:
            if not isinstance(lot, dict):
                continue
            objets = [
                (o.get("itemType") or {}).get("name", "?")
                for o in lot.get("bundleContent") or []
            ]
            if objets:
                lignes.append(f"{lot.get('bundleType', '?')} : {', '.join(objets)}")
        return "\n".join(lignes) or "Pas de données de craft."

    async def _predator(self) -> str:
        """Seuil Predator. L'API ne publie plus que `RP` : les arènes ont disparu."""
        data = await self._client.get("predator")
        if isinstance(data, str):
            return data
        rp = (data or {}).get("RP") or {}
        lignes = []
        for cle, nom in (("PC", "PC"), ("PS4", "PS4"), ("X1", "Xbox")):
            info = rp.get(cle)
            if not isinstance(info, dict):
                continue
            ligne = f"{nom} : {info.get('val', '?')} RP pour être Predator"
            if info.get("totalMastersAndPreds") is not None:
                ligne += f" ({info['totalMastersAndPreds']} Masters+Preds)"
            lignes.append(ligne)
        return "\n".join(lignes) or "Pas de données Predator."

    async def _server_status(self) -> str:
        data = await self._client.get("servers")
        if isinstance(data, str):
            return data
        lignes = []
        for groupe in (data or {}).values():
            if not isinstance(groupe, dict):
                continue
            for nom, info in groupe.items():
                if isinstance(info, dict) and info.get("Status"):
                    marque = "✅" if info["Status"] == "UP" else "❌"
                    lignes.append(f"{marque} {nom} : {info['Status']}")
        return "\n".join(lignes[:10]) or "Pas de données serveurs."
