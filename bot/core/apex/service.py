# bot/core/apex/service.py
"""Les actions Apex offertes au LLM, rendues en texte lisible.

Le service ne décide de rien : il va chercher, met en forme, et dit clairement
quand il n'a pas. Ce qu'il ne sait pas faire est annoncé dans la description de
l'outil, pour que le modèle n'aille pas le chercher ailleurs.
"""
from __future__ import annotations

import os
from typing import Any

from loguru import logger

from bot.core.apex.client import ApexClient
from bot.core.apex.reader import PlayerProfile, read_profile
from bot.core.apex.widgets import (
    APEX_PANELS,
    craft_panel,
    map_panel,
    predator_panel,
    rank_panel,
    servers_panel,
    stats_panel,
    status_panel,
)


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

    def __init__(self, client: ApexClient | None = None, db: Any = None) -> None:
        self._client = client or ApexClient(os.environ.get("APEX_API_KEY", ""))
        self._db = db

    @property
    def available(self) -> bool:
        return bool(self._client.available)

    def get_tool_definition(self) -> dict:
        from bot.core.apex.tool import APEX_LEGENDS_TOOL
        return APEX_LEGENDS_TOOL

    async def execute(
        self,
        action: str,
        player_name: str = "",
        platform: str = "PC",
        *,
        remember: bool = False,
        requester: str | None = None,
        requester_name: str = "",
    ) -> str:
        """Exécute une action. `requester` vient du HANDLER, jamais du modèle :
        c'est ce qui empêche quiconque de déclarer le compte d'un autre."""
        if action == "player_stats":
            return await self._player_stats(
                player_name, platform,
                remember=remember, requester=requester, requester_name=requester_name,
            )
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

    async def _player_stats(
        self,
        player_name: str,
        platform: str,
        *,
        remember: bool = False,
        requester: str | None = None,
        requester_name: str = "",
    ) -> str:
        cherche, platform = await self._resolve(player_name, platform, requester)
        uid = await self._resolve_uid(requester, player_name)
        if not cherche and not uid:
            return "Il me faut un pseudo Apex pour chercher."
        data = await self._client.get(
            "bridge", {**({"uid": uid} if uid else {"player": cherche}),
                       "platform": platform or "PC"}
        )
        if isinstance(data, str):
            return data
        profil = read_profile(data)
        if profil is None:
            erreur = data.get("Error") if isinstance(data, dict) else ""
            return f"{cherche} : pas trouvé sur l'API Apex ({erreur or 'compte inconnu'})."
        if remember and requester:
            await self._remember(profil, cherche, platform, requester, requester_name)
        return self._render_profile(profil)

    async def fetch_profile(
        self, player: str, platform: str = "PC", uid: str | None = None
    ) -> PlayerProfile | None:
        """Le profil d'un joueur, ou None. Brique commune au texte, aux panneaux
        et au suivi passif — un seul endroit qui sait interroger `/bridge`.

        `uid` l'emporte sur le pseudo quand on l'a : un pseudo se change, un uid
        non — et l'API accepte les deux.
        """
        if not player and not uid:
            return None
        params = {"uid": uid} if uid else {"player": player}
        data = await self._client.get("bridge", {**params, "platform": platform or "PC"})
        if isinstance(data, str):
            return None
        return read_profile(data)

    async def _resolve(
        self, player_name: str, platform: str, requester: str | None
    ) -> tuple[str, str]:
        """Le pseudo Apex à interroger, et sur quelle plateforme.

        Un pseudo de plateforme (« xeforce_ ») est traduit en compte Apex si la
        personne l'a déclaré ; sans pseudo du tout, on prend celui du demandeur.
        Faute de liaison, on interroge tel quel — l'API tranchera.
        """
        if self._db is None:
            return player_name, platform
        try:
            lien = (
                await self._db.apex_find_by_display_name(player_name)
                if player_name
                else (await self._db.apex_get_account(requester) if requester else None)
            )
        except Exception as e:                       # une base grippée ne casse pas la recherche
            logger.warning("Apex: lecture des comptes liés impossible: {e}", e=e)
            return player_name, platform
        if lien is None:
            return player_name, platform
        return lien["apex_name"], lien["apex_platform"] or platform

    async def _resolve_uid(self, requester: str | None, player_name: str) -> str | None:
        """L'uid mémorisé du joueur visé, s'il y en a un."""
        if self._db is None:
            return None
        try:
            lien = (
                await self._db.apex_find_by_display_name(player_name)
                if player_name
                else (await self._db.apex_get_account(requester) if requester else None)
            )
        except Exception:  # noqa: BLE001 — l'uid est un confort, pas une condition
            return None
        return (lien["uid"] or None) if lien else None

    async def _remember(
        self, profil, cherche: str, platform: str, requester: str, requester_name: str
    ) -> None:
        """Écrit la liaison — pour le DEMANDEUR, et seulement si le compte existe."""
        if self._db is None:
            return
        try:
            await self._db.apex_link_account(
                identity=requester,
                display_name=requester_name or requester,
                apex_name=cherche,
                apex_platform=platform or "PC",
                uid=profil.uid or None,
            )
            logger.info(
                "Apex: compte {name} lié à {who}", name=cherche, who=requester_name or requester
            )
        except Exception as e:
            logger.warning("Apex: impossible de mémoriser le compte: {e}", e=e)

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

    # ── Les panneaux de l'overlay ─────────────────────────────────────────────

    async def build_panel(
        self,
        panel: str,
        player: str = "",
        platform: str = "PC",
        *,
        requester: str | None = None,
    ) -> dict | None:
        """Le contenu d'un panneau d'overlay, prêt à publier — ou None.

        Le modèle ne fournit aucun chiffre : il nomme un panneau, on va chercher
        la donnée. None quand elle manque, pour ne jamais afficher de carte vide.
        """
        if panel not in APEX_PANELS:
            return None
        if panel in ("rank", "status", "stats"):
            cherche, platform = await self._resolve(player, platform, requester)
            uid = await self._resolve_uid(requester, player)
            if not cherche and not uid:
                return None
            data = await self._client.get(
                "bridge", {**({"uid": uid} if uid else {"player": cherche}),
                           "platform": platform or "PC"}
            )
            if isinstance(data, str):
                return None
            profil = read_profile(data)
            built = {"rank": rank_panel, "status": status_panel, "stats": stats_panel}[panel](profil)
        else:
            endpoint, params, builder = {
                "map": ("maprotation", {"version": "2"}, map_panel),
                "craft": ("crafting", None, craft_panel),
                "predator": ("predator", None, predator_panel),
                "servers": ("servers", None, servers_panel),
            }[panel]
            data = await self._client.get(endpoint, params)
            if isinstance(data, str):
                return None
            built = builder(data)
        return {"kind": f"apex_{panel}", **built} if built else None

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
