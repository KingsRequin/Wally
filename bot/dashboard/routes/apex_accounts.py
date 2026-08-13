# bot/dashboard/routes/apex_accounts.py
"""Le registre des profils Apex, lu et corrigé depuis le panneau admin.

Le registre se remplit tout seul — chat, panneaux d'overlay, sonde du watcher —
et un rapprochement approximatif peut y inscrire un pseudo qui mène au mauvais
joueur. Sans écran pour le lire, l'erreur reste invisible ; sans geste pour la
retirer, elle est définitive. D'où ces routes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from bot.core.apex.service import _uid_valide, lien_profil

router = APIRouter()


class LinkRequest(BaseModel):
    identity: str
    display_name: str = ""
    ref: str


@router.get("/apex/profiles")
async def list_apex_profiles(request: Request):
    """Le registre entier : chaque profil, ses pseudos, son propriétaire.

    Le lien est calculé ici et pas côté navigateur : la forme d'URL qui porte un
    uid est une connaissance du domaine (l'autre ne contient qu'un pseudo, que
    l'API refuse), elle n'a pas à être réécrite dans le front.
    """
    db = request.app.state.wally.db
    profils = await db.apex_list_profiles()
    for p in profils:
        p["url"] = lien_profil(p["uid"], p["platform"])
    return {"profiles": profils}


@router.delete("/apex/profiles/{uid}/names/{name:path}")
async def forget_apex_name(uid: str, name: str, request: Request):
    """Oublie un pseudo qui menait à ce profil.

    Le nom OFFICIEL est refusé : le prochain scan du profil le réinscrirait, et
    proposer un geste sans effet durable serait mentir sur ce qu'il fait.
    """
    db = request.app.state.wally.db
    profil = await db.fetch_one(
        "SELECT apex_name FROM apex_profiles WHERE uid = ?", (uid,)
    )
    if profil is None:
        raise HTTPException(404, "Profil inconnu")
    if str(profil["apex_name"]).lower() == name.lower():
        raise HTTPException(
            409,
            "C'est le nom officiel du compte : le prochain scan le réinscrirait. "
            "Supprime le profil entier si tu veux le voir disparaître.",
        )
    if not await db.apex_forget_name(uid, name):
        raise HTTPException(404, "Ce nom ne mène pas à ce profil")
    logger.info("Apex: alias « {n} » retiré du profil {uid}", n=name, uid=uid)
    return {"status": "ok"}


@router.delete("/apex/profiles/{uid}")
async def forget_apex_profile(uid: str, request: Request):
    db = request.app.state.wally.db
    await db.apex_forget_profile(uid)
    logger.info("Apex: profil {uid} retiré du registre", uid=uid)
    return {"status": "ok"}


@router.post("/apex/link")
async def link_apex_account(payload: LinkRequest, request: Request):
    """Rattache une personne à un compte Apex, sans passer par le chat.

    `ref` accepte ce qu'on a sous la main : l'URL du profil, un uid, ou un
    pseudo. Le compte est VÉRIFIÉ auprès de l'API avant d'écrire quoi que ce
    soit — écrire une liaison non vérifiée laisserait en base un uid mort que
    plus rien ne viendrait corriger, et Wally répondrait « aucun relevé » sans
    que personne comprenne pourquoi.
    """
    state = request.app.state.wally
    apex = getattr(state, "apex", None)
    if apex is None:
        raise HTTPException(503, "Service Apex indisponible")
    ref = payload.ref.strip()
    if not payload.identity.strip() or not ref:
        raise HTTPException(400, "Il faut une personne et un compte Apex")

    uid = _uid_valide(ref)
    profil = await apex.fetch_profile("" if uid else ref, uid=uid or None)
    if profil is None or not profil.uid:
        raise HTTPException(
            404,
            "Aucun compte Apex derrière cette référence. La recherche par pseudo "
            "rate des comptes bien réels : donne plutôt le lien de la page "
            "apexlegendsstatus.com qui contient l'uid.",
        )

    await state.db.apex_link_account(
        identity=payload.identity.strip(),
        display_name=payload.display_name.strip() or payload.identity.strip(),
        apex_name=profil.name,
        apex_platform=profil.platform or "PC",
        uid=profil.uid,
    )
    logger.info(
        "Apex: {name} lié à {who} depuis le panneau admin",
        name=profil.name, who=payload.identity,
    )
    return {
        "status": "ok",
        "uid": profil.uid,
        "apex_name": profil.name,
        "platform": profil.platform or "PC",
        "url": lien_profil(profil.uid, profil.platform),
    }


@router.delete("/apex/link/{identity:path}")
async def unlink_apex_account(identity: str, request: Request):
    db = request.app.state.wally.db
    await db.apex_unlink_account(identity)
    logger.info("Apex: liaison de {who} retirée", who=identity)
    return {"status": "ok"}
