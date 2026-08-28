# bot/dashboard/routes/person.py
"""Tout ce que Wally sait d'UNE personne, en une requête.

Avant la refonte du 2026-08-28, répondre à « que sait Wally de KingsRequin ? »
demandait quatre onglets et autant d'endpoints : les mémoires dans
Utilisateurs, le compte Apex dans Comptes Apex, le statut d'écoute dans
Ignorés, les surnoms dans les alias. Rien ne rassemblait ces morceaux, et
c'était pourtant toujours la même question.

Le point délicat est l'IDENTITÉ. Une personne peut avoir un compte Discord et
un compte Twitch liés : ses faits sont alors répartis entre `discord:123` et
`twitch:pseudo`, et n'interroger que l'un des deux en montre la moitié sans
rien dire. Cette route résout d'abord le groupe d'identités, puis interroge
CHACUNE.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def _plateforme(identite: str) -> str:
    return identite.split(":", 1)[0] if ":" in identite else ""


def _brut(identite: str) -> str:
    return identite.split(":", 1)[1] if ":" in identite else identite


def _horodatage(valeur: object) -> float:
    """Un timestamp exploitable, 0.0 si la colonne ne portait rien de lisible.

    `memory_users.last_updated` est un REAL, mais il transite par un
    `dict[str, Any]` : sans conversion explicite, la soustraction plus bas
    accepterait une chaîne et lèverait en production plutôt qu'au typage.
    """
    try:
        return float(valeur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


async def _groupe_didentites(db, identite: str) -> tuple[str, list[str]]:
    """(identité canonique, toutes les identités du groupe).

    Une liaison acceptée range une identité comme `alias_id` d'un
    `canonical_id`. On accepte les DEUX en entrée : un lien partagé peut viser
    l'alias, et renvoyer 404 parce que la personne a été fusionnée depuis
    serait absurde.
    """
    liens = await db.list_link_proposals(status="accepted") or []
    canonique = identite
    for lien in liens:
        if lien["alias_id"] == identite:
            canonique = lien["canonical_id"]
            break
    groupe = [canonique]
    for lien in liens:
        if lien["canonical_id"] == canonique and lien["alias_id"] not in groupe:
            groupe.append(lien["alias_id"])
    return canonique, groupe


def _fait_en_dict(f) -> dict:
    return {
        "id": f.id,
        "content": f.content,
        "category": f.category.value,
        "subject": f.subject,
        "predicate": f.predicate,
        "object": f.object_,
        "confidence": f.confidence,
        "importance": f.importance,
        "origin": f.origin,
        "source": f.source,
        "user_id": f.user_id,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "expires_at": f.expires_at.isoformat() if f.expires_at else None,
    }


@router.get("/person/{identite:path}")
async def fiche_personne(identite: str, request: Request) -> dict:
    """La fiche complète. `identite` est préfixée : `discord:123`, `twitch:x`."""
    if ":" not in identite:
        raise HTTPException(
            status_code=400,
            detail="identité attendue sous la forme plateforme:id (ex. discord:123)",
        )
    etat = request.app.state.wally
    db = etat.db

    canonique, groupe = await _groupe_didentites(db, identite)

    gens = {u["user_id"]: u for u in await db.list_memory_users(include_no_memory=True) or []}
    if canonique not in gens and not any(g in gens for g in groupe):
        raise HTTPException(status_code=404, detail="personne inconnue")

    # ── Les identités du groupe, chacune avec ce qu'on sait d'elle ──
    identites = []
    for uid in groupe:
        u = gens.get(uid) or {}
        identites.append({
            "identity": uid,
            "plateforme": _plateforme(uid),
            "nom": u.get("username") or _brut(uid),
            "avatar_url": u.get("avatar_url"),
            "vu_le": u.get("last_updated"),
        })

    principale = next((i for i in identites if i["identity"] == canonique), identites[0])
    # L'avatar Discord d'abord : Twitch n'en fournit pas toujours, et une
    # pastille grise là où un visage existe rend la liste illisible.
    avatar = next(
        (i["avatar_url"] for i in identites
         if i["plateforme"] == "discord" and i["avatar_url"]),
        next((i["avatar_url"] for i in identites if i["avatar_url"]), None),
    )

    # ── Trust et love : par identité, on garde le plus haut ──
    # Un compte Twitch fraîchement lié part à zéro ; afficher ce zéro parce
    # qu'il se trouve être l'identité canonique effacerait dix mois de relation.
    trust = love = 0.0
    for uid in groupe:
        trust = max(trust, await db.get_trust_score(_plateforme(uid), _brut(uid)))
        love = max(love, await db.get_love_score(_plateforme(uid), _brut(uid)))

    # ── Les faits, de TOUTES les identités du groupe ──
    store = getattr(etat, "fact_store", None)
    memoires: list[dict] = []
    if store is not None:
        for uid in groupe:
            memoires.extend(_fait_en_dict(f) for f in await store.get_by_user(uid))
    memoires.sort(key=lambda m: m["created_at"] or "", reverse=True)

    alias = [a["nickname"] for a in await db.list_aliases(canonical_uid=canonique) or []]

    compte_apex = await db.apex_account_for_person(canonique)

    # ── Les notes qui MENTIONNENT la personne ──
    # `persistent_notes` est une table GLOBALE : pas de colonne d'utilisateur,
    # une note n'appartient à personne. On ne peut donc pas rendre « ses »
    # notes — seulement celles où l'un de ses noms apparaît. Le libellé côté
    # panneau le dit, pour ne pas faire passer une recherche pour une propriété.
    noms = {principale["nom"], *alias, *(i["nom"] for i in identites)}
    noms = {n.lower() for n in noms if n and len(n) >= 3}
    notes = [
        n for n in await db.get_persistent_notes() or []
        if any(m in (n["title"] + " " + n["content"]).lower() for m in noms)
    ]

    # `last_updated` traverse un `dict[str, Any]` : le forcer en float ici,
    # une seule fois, plutôt que de laisser la soustraction plus bas décider.
    vu_le = max((_horodatage(i["vu_le"]) for i in identites), default=0.0)

    return {
        "identity": canonique,
        "nom": principale["nom"],
        "avatar_url": avatar,
        "plateforme": principale["plateforme"],
        "identites": identites,
        "alias": alias,
        "trust": round(trust, 3),
        "love": round(love, 3),
        "memoires": memoires,
        "notes": notes,
        "apex": dict(compte_apex) if compte_apex else None,
        "ignore": await _est_ignoree(etat, identites),
        "vu_le": vu_le or None,
        "vu_depuis_heures": round((time.time() - vu_le) / 3600, 1) if vu_le else None,
    }


async def _est_ignoree(etat, identites: list[dict]) -> bool:
    """Wally écoute-t-il cette personne ?

    Deux mécanismes distincts, qui ne se voient pas l'un l'autre : la liste
    Twitch de `config.twitch.ignored_users`, et la table des bannis du chat web
    côté Discord. En interroger un seul répondrait « écouté » à propos de
    quelqu'un que l'autre fait taire — exactement ce que l'onglet « Ignorés »
    a été créé pour arrêter.

    Le socle de bots câblé en dur (`_KNOWN_BOTS`) n'est PAS consulté : il ne
    désigne aucune personne connue de la mémoire, et une identité qui arrive
    jusqu'ici en vient forcément.
    """
    ignores = {
        str(n).lower().lstrip("@")
        for n in (getattr(etat.config.twitch, "ignored_users", None) or [])
    }
    bannis = {
        str(b.get("discord_id") or "") for b in await etat.db.list_chat_bans() or []
    }
    for i in identites:
        if i["plateforme"] == "twitch":
            if _brut(i["identity"]).lower() in ignores:
                return True
            if (i["nom"] or "").lower() in ignores:
                return True
        elif i["plateforme"] == "discord" and _brut(i["identity"]) in bannis:
            return True
    return False
