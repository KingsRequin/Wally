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
    # Le même classement RESTREINT à la plateforme du joueur (`rankPlatformSpecific`).
    # L'API le renvoie à chaque appel et il était jeté. C'est souvent le chiffre
    # parlant : Azraël est 3ᵉ mondial aux kills avec Fuse, mais 2ᵉ sur PC, et
    # 10ᵉ mondial aux wins contre 3ᵉ sur PC.
    #
    # Ce n'est PAS un rang par pays : celui-là vivrait dans `/leaderboard`, que
    # notre clé n'est pas autorisée à interroger (« You must be whitelisted »,
    # vérifié le 2026-08-10). `/bridge` ne porte aucune notion de pays.
    platform_pos: int | None = None
    platform_percent: float | None = None


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
    # Les mêmes notions, mais par légende — `{"Fuse": {"kills": ...}}`. Une
    # légende sans tracker épinglé est absente, jamais à zéro.
    legend_stats: dict[str, dict[str, StatValue]] = field(default_factory=dict)


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
    # `or {}` à CHAQUE étage : le défaut de `.get()` ne couvre qu'une clé
    # absente, or l'API rend parfois `"legends": null` — et `.get` sur None lève.
    #
    # Et `or {}` ne suffit pas non plus : une LISTE est vraie, donc elle traverse
    # le `or` et fait lever le `.get()` suivant. L'API ne promet aucun type ; on
    # vérifie donc la forme, pas seulement la présence.
    toutes = (payload.get("legends") or {}).get("all") or {}
    if not isinstance(toutes, dict):
        return {}
    glob = toutes.get("Global") or {}
    if not isinstance(glob, dict):
        return {}
    entrees = glob.get("data")
    for item in entrees if isinstance(entrees, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("name", "")).lower()
        rank = item.get("rank") or {}
        pos = _positive_int(rank.get("rankPos"))
        pct = _num(rank.get("topPercent"))
        if label and (pos is not None or pct is not None):
            found[label] = (pos, pct)
    return found


def _read_stats(payload: dict) -> dict[str, StatValue]:
    """Les notions connues, telles que ce joueur les publie.

    Plusieurs trackers peuvent porter le MÊME libellé et se compléter : Azraël a
    « BR Kills » deux fois, `specialEvent_kills` = 92 182 et `kills` = 10 142.
    Ils s'ADDITIONNENT — la preuve est dans ses propres données, la somme de ses
    « BR Kills » par légende vaut exactement 102 324, soit les deux réunis.

    On gardait le premier rencontré et on jetait l'autre : Wally annonçait
    « 92 182 kills » à qui en avait plus de cent mille, avec un aplomb parfait.
    Une valeur amputée de 10 % ne se voit pas — elle est juste fausse.
    """
    total = payload.get("total") or {}
    if not isinstance(total, dict):
        return {}
    # index libellé → (libellé d'origine, somme des trackers de ce libellé)
    by_label: dict[str, tuple[str, int]] = {}
    for entry in total.values():
        if not isinstance(entry, dict):
            continue
        label = entry.get("name")
        value = _num(entry.get("value"))
        if not label or value is None:
            continue
        cle = str(label).lower()
        precedent = by_label.get(cle)
        cumul = int(value) + (precedent[1] if precedent else 0)
        by_label[cle] = (str(label), cumul)

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


def _read_legend_stats(payload: dict) -> dict[str, dict[str, StatValue]]:
    """Les statistiques PAR LÉGENDE, telles que ce joueur les publie.

    Renvoie `{"Fuse": {"kills": StatValue(...), ...}, ...}`. Une légende dont le
    joueur n'a épinglé aucun tracker n'apparaît PAS — son bloc ne contient que
    `ImgAssets`. C'est volontaire : « 0 kill avec Fuse » serait un mensonge là où
    la vérité est « il ne suit pas ce chiffre ».

    Trois formes réelles à encaisser, relevées sur les comptes d'Azraël et de
    KingsRequin :

    · `Global` est rangé parmi les légendes mais n'en est pas une — il porte les
      totaux de carrière et le rang mondial. Le confondre avec une légende
      annonçait déjà « 92 182 kills, 3ᵉ mondial » au lieu de « pas de rang ».
    · Deux entrées peuvent porter le MÊME libellé sous une même légende :
      Rampart chez Azraël a « BR Kills » deux fois, `kills` = 982 et
      `specialEvent_kills` = 2285. Ce ne sont pas des doublons mais deux
      compteurs qui s'ADDITIONNENT, comme au niveau global — la somme de tous
      ses « BR Kills » par légende vaut exactement son total, 102 324. Le rang
      mondial retenu est celui du tracker DOMINANT : un classement porte sur un
      compteur, jamais sur une somme.
    · Un bloc de légende peut ne pas être un dict, et `data` peut ne pas être une
      liste. L'API ne garantit aucune forme.
    """
    par_legende: dict[str, dict[str, StatValue]] = {}
    toutes = ((payload.get("legends") or {}).get("all") or {})
    if not isinstance(toutes, dict):
        return {}

    for nom, bloc in toutes.items():
        if not isinstance(bloc, dict) or str(nom).lower() == "global":
            continue
        entrees = bloc.get("data")
        if not isinstance(entrees, list):
            continue

        # libellé → (libellé, cumul, rangMondial, top%, rangPlateforme,
        #            top% plateforme, valeur du tracker dominant)
        par_libelle: dict[str, tuple] = {}
        for entree in entrees:
            if not isinstance(entree, dict):
                continue
            libelle = entree.get("name")
            valeur = _num(entree.get("value"))
            if not libelle or valeur is None:
                continue
            cle = str(libelle).lower()
            rang = entree.get("rank") or {}
            plateforme = entree.get("rankPlatformSpecific") or {}
            # `NOT_CALCULATED_YET` là où on attend un entier : `_num` le rejette,
            # donc l'absence reste une absence.
            rangs = (
                _positive_int(rang.get("rankPos")), _num(rang.get("topPercent")),
                _positive_int(plateforme.get("rankPos")),
                _num(plateforme.get("topPercent")),
            )
            ancien = par_libelle.get(cle)
            if ancien is None:
                par_libelle[cle] = (str(libelle), int(valeur), *rangs, int(valeur))
                continue
            # Valeurs cumulées ; rangs empruntés au tracker dominant, dont on
            # garde la valeur à part pour savoir lequel domine.
            domine = int(valeur) > ancien[6]
            par_libelle[cle] = (
                ancien[0], ancien[1] + int(valeur),
                *(rangs if domine else ancien[2:6]),
                max(int(valeur), ancien[6]),
            )

        notions: dict[str, StatValue] = {}
        for notion, alias_possibles in STAT_ALIASES.items():
            for alias in alias_possibles:
                trouve = par_libelle.get(alias.lower())
                if trouve is None:
                    continue
                notions[notion] = StatValue(
                    label=trouve[0], value=trouve[1],
                    world_pos=trouve[2], top_percent=trouve[3],
                    platform_pos=trouve[4], platform_percent=trouve[5],
                )
                break
        if notions:
            par_legende[str(nom)] = notions
    return par_legende


def _read_skin(payload: dict) -> str | None:
    """Le skin de la légende jouée — de la couleur pour l'overlay, rien de plus."""
    info = ((payload.get("legends") or {}).get("selected") or {}).get("gameInfo") or {}
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
        legend_stats=_read_legend_stats(payload),
    )
