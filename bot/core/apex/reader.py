# bot/core/apex/reader.py
"""Interprète une réponse `/bridge` sans supposer sa forme.

Le piège, vérifié sur deux comptes réels le 2026-08-08 : les statistiques ne
portent pas les mêmes clés d'un joueur à l'autre. Les kills de KingsRequin sont
dans `career_kills` (« Career Kills »), ceux d'Azraël dans `specialEvent_kills`
(« BR Kills »). Les trackers dépendent de ce que chacun a épinglé en jeu.

D'où la règle : on cherche une NOTION par ses libellés connus, jamais par une
clé supposée, et ce qu'on ne trouve pas reste introuvé — jamais 0.

Aucun accès réseau ici : c'est ce qui rend le piège testable sur fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Une notion → les libellés sous lesquels l'API la publie, du plus précis au
# plus générique. La casse est ignorée à la comparaison.
STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "kills": ("Career Kills", "BR Kills", "Kills"),
    "wins": ("Career Wins", "BR Wins", "Wins"),
    "damage": ("Career Damage", "BR Damage", "Damage"),
    "revives": ("Career Revives", "BR Revives", "Revives"),
    "headshots": ("Career Headshots", "BR Headshots", "Headshots"),
    "matches": ("Games Played", "BR Games Played", "Matches Played"),
}


@dataclass(frozen=True)
class StatValue:
    label: str
    value: int
    world_pos: int | None = None
    top_percent: float | None = None


@dataclass(frozen=True)
class RankInfo:
    name: str
    div: int
    score: int
    img: str = ""
    top_percent: float | None = None
    ladder_pos: int | None = None


@dataclass(frozen=True)
class PlayerProfile:
    name: str
    uid: str
    platform: str
    level: int
    level_percent: int
    avatar: str
    banned: bool
    ban_reason: str
    rank: RankInfo | None
    state: str
    in_game: bool
    legend: str | None
    skin: str | None
    stats: dict[str, StatValue] = field(default_factory=dict)


def _num(value: Any) -> float | None:
    """Le nombre, ou None. L'API glisse des phrases là où on attend un chiffre :
    `ALStopPercent` vaut « No game this split » pour qui n'a pas joué du split."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    """Une position de classement. `-1` signifie « non classé » : c'est une
    absence, pas un rang."""
    number = _num(value)
    if number is None or number < 0:
        return None
    return int(number)


def _world_ranks(payload: dict) -> dict[str, tuple[int | None, float | None]]:
    """Position mondiale par libellé de tracker, lue dans le SEUL bloc `Global`.

    Les mêmes libellés existent sous chaque légende, mais ils y comptent autre
    chose : « BR Kills » sous Revenant, c'est le classement des kills faits AVEC
    Revenant. Les rapprocher du total carrière donnait « 92 182 kills, 3ᵉ
    mondial » — faux d'un facteur mille. Sans bloc `Global`, ce joueur n'a
    simplement pas de rang mondial, et on n'en invente pas.
    """
    found: dict[str, tuple[int | None, float | None]] = {}
    glob = (payload.get("legends", {}).get("all", {}) or {}).get("Global") or {}
    for item in glob.get("data") or []:
        label = str(item.get("name", "")).lower()
        rank = item.get("rank") or {}
        pos = _positive_int(rank.get("rankPos"))
        pct = _num(rank.get("topPercent"))
        if label and (pos is not None or pct is not None):
            found[label] = (pos, pct)
    return found


def _read_stats(payload: dict) -> dict[str, StatValue]:
    """Les notions connues, telles que ce joueur les publie."""
    total = payload.get("total") or {}
    if not isinstance(total, dict):
        return {}
    # index libellé → (libellé d'origine, valeur)
    by_label: dict[str, tuple[str, int]] = {}
    for entry in total.values():
        if not isinstance(entry, dict):
            continue
        label = entry.get("name")
        value = _num(entry.get("value"))
        if not label or value is None:
            continue
        by_label.setdefault(str(label).lower(), (str(label), int(value)))

    ranks = _world_ranks(payload)
    stats: dict[str, StatValue] = {}
    for notion, aliases in STAT_ALIASES.items():
        for alias in aliases:
            hit = by_label.get(alias.lower())
            if hit is None:
                continue
            pos, pct = ranks.get(alias.lower(), (None, None))
            stats[notion] = StatValue(label=hit[0], value=hit[1], world_pos=pos, top_percent=pct)
            break
    return stats


def _read_skin(payload: dict) -> str | None:
    """Le skin de la légende jouée — de la couleur pour l'overlay, rien de plus."""
    info = (payload.get("legends", {}).get("selected") or {}).get("gameInfo") or {}
    skin = info.get("skin")
    return str(skin) if skin else None


def _read_rank(payload: dict) -> RankInfo | None:
    rank = (payload.get("global") or {}).get("rank") or {}
    if not rank.get("rankName"):
        return None
    return RankInfo(
        name=str(rank.get("rankName")),
        div=int(_num(rank.get("rankDiv")) or 0),
        score=int(_num(rank.get("rankScore")) or 0),
        img=str(rank.get("rankImg") or ""),
        top_percent=_num(rank.get("ALStopPercent")),
        ladder_pos=_positive_int(rank.get("ladderPosPlatform")),
    )


def read_profile(payload: Any) -> PlayerProfile | None:
    """Le profil, ou None si la réponse n'en contient pas."""
    if not isinstance(payload, dict) or "Error" in payload:
        return None
    glob = payload.get("global")
    if not isinstance(glob, dict) or not glob.get("name"):
        return None

    bans = glob.get("bans") or {}
    realtime = payload.get("realtime") or {}
    return PlayerProfile(
        name=str(glob.get("name")),
        uid=str(glob.get("uid") or ""),
        platform=str(glob.get("platform") or ""),
        level=int(_num(glob.get("level")) or 0),
        level_percent=int(_num(glob.get("toNextLevelPercent")) or 0),
        avatar=str(glob.get("avatar") or ""),
        banned=bool(bans.get("isActive")),
        ban_reason=str(bans.get("last_banReason") or ""),
        rank=_read_rank(payload),
        state=str(realtime.get("currentStateAsText") or ""),
        in_game=bool(_num(realtime.get("isInGame"))),
        legend=str(realtime.get("selectedLegend")) if realtime.get("selectedLegend") else None,
        skin=_read_skin(payload),
        stats=_read_stats(payload),
    )
