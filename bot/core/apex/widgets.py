# bot/core/apex/widgets.py
"""Les panneaux Apex de l'overlay, construits côté serveur.

Le modèle choisit ce qu'il montre et le commente ; il ne fournit AUCUN chiffre.
C'est ce qui distingue ces panneaux du widget `stats` générique, où Wally
recopiait à la main des valeurs qu'il venait de lire — et pouvait se tromper.

Chaque fonction rend un dict sérialisable, ou `None` quand il n'y a rien à
montrer : une carte creuse à l'écran est pire que pas de carte.
"""
from __future__ import annotations

from typing import Any

from bot.core.apex.reader import PlayerProfile

APEX_PANELS = ("rank", "status", "stats", "map", "craft", "predator", "servers")

# Les modes de rotation, dans l'ordre d'intérêt (mêmes libellés que le service).
_MODES = (
    ("battle_royale", "Battle Royale"),
    ("ranked", "Ranked"),
    ("ltm", "Mode temporaire"),
    ("wildcard", "Wildcard"),
)

# Un panneau tient dans 560×460 : au-delà, le contenu est rogné.
_MAX_ROWS = 6


def _seconds(timer: Any) -> int:
    """« 01:26:30 » → 5190. L'écran a besoin d'un décompte vivant, pas d'un texte."""
    parts = str(timer or "").split(":")
    if not parts or not all(p.strip().isdigit() for p in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def rank_panel(profile: PlayerProfile | None) -> dict | None:
    if profile is None or profile.rank is None:
        return None
    return {
        "player": profile.name,
        "rank_name": profile.rank.name,
        "div": profile.rank.div,
        "score": profile.rank.score,
        "img": profile.rank.img,
        "top_percent": profile.rank.top_percent,
        "ladder_pos": profile.rank.ladder_pos,
    }


def status_panel(profile: PlayerProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "player": profile.name,
        "state": profile.state,
        "in_game": profile.in_game,
        "legend": profile.legend,
        "skin": profile.skin,
        "level": profile.level,
        "level_percent": profile.level_percent,
        "avatar": profile.avatar,
        "banned": profile.banned,
    }


def stats_panel(profile: PlayerProfile | None) -> dict | None:
    if profile is None or not profile.stats:
        return None
    return {
        "player": profile.name,
        "avatar": profile.avatar,
        "rows": [
            {
                "label": stat.label,
                "value": stat.value,
                "world_pos": stat.world_pos,
                "top_percent": stat.top_percent,
            }
            for stat in list(profile.stats.values())[:_MAX_ROWS]
        ],
    }


def map_panel(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    modes = []
    for cle, nom in _MODES:
        mode = raw.get(cle)
        if not isinstance(mode, dict):
            continue
        courant = mode.get("current") or {}
        suivant = mode.get("next") or {}
        if not courant.get("map"):
            continue
        modes.append({
            "name": nom,
            "map": str(courant["map"]),
            "remaining_s": _seconds(courant.get("remainingTimer")),
            "next": str(suivant.get("map") or ""),
        })
    return {"modes": modes} if modes else None


def craft_panel(raw: Any) -> dict | None:
    if not isinstance(raw, list):
        return None
    bundles = []
    for lot in raw:
        if not isinstance(lot, dict):
            continue
        items = [
            str((o.get("itemType") or {}).get("name") or "")
            for o in lot.get("bundleContent") or []
        ]
        items = [i for i in items if i]
        if items:
            bundles.append({"type": str(lot.get("bundleType") or "?"), "items": items[:4]})
    return {"bundles": bundles[:_MAX_ROWS]} if bundles else None


def predator_panel(raw: Any) -> dict | None:
    """Seuil Predator. L'API ne publie plus que `RP` — les arènes ont disparu."""
    rp = (raw or {}).get("RP") if isinstance(raw, dict) else None
    if not isinstance(rp, dict):
        return None
    rows = []
    for cle, nom in (("PC", "PC"), ("PS4", "PS4"), ("X1", "Xbox")):
        info = rp.get(cle)
        if not isinstance(info, dict):
            continue
        try:
            valeur = int(info.get("val"))
        except (TypeError, ValueError):
            continue
        rows.append({
            "platform": nom,
            "rp": valeur,
            "count": info.get("totalMastersAndPreds"),
        })
    return {"rows": rows} if rows else None


def servers_panel(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    rows = []
    for groupe in raw.values():
        if not isinstance(groupe, dict):
            continue
        for nom, info in groupe.items():
            if isinstance(info, dict) and info.get("Status"):
                rows.append({
                    "name": str(nom),
                    "status": str(info["Status"]),
                    "up": info["Status"] == "UP",
                })
    return {"rows": rows[:_MAX_ROWS]} if rows else None
