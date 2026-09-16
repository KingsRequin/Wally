# bot/dashboard/routes/recompenses.py
"""Récompenses de points de chaîne : lister, modifier, supprimer, réactiver.

Tout passe par `GestionRecompenses` (`bot/twitch/recompenses.py`), l'objet
même qui les arme au boot : une modification part chez Twitch dans la seconde,
sans redémarrage, et la config est rangée tout de suite (`config.save()`).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bot.twitch.api import PROMPT_MAX, TITRE_MAX
from bot.twitch.recompenses import DEFINITIONS

admin_router = APIRouter()

# Plafond Twitch d'une recharge globale : 7 jours.
RECHARGE_MAX_S = 604800


class ModifRecompense(BaseModel):
    titre: str | None = None
    cout: int | None = None
    prompt: str | None = None
    recharge_s: int | None = None


class ModifPrixDynamique(BaseModel):
    hausse_pct: float | None = None
    demi_vie_minutes: float | None = None


def _gestion(request: Request):
    bot = request.app.state.wally.twitch_bot
    gestion = getattr(bot, "recompenses", None)
    if gestion is None:
        raise HTTPException(503, "Twitch n'est pas connecté : récompenses indisponibles")
    return gestion


def _conf(request: Request, cle: str):
    if cle not in DEFINITIONS:
        raise HTTPException(404, f"Récompense inconnue : {cle}")
    rc = request.app.state.wally.config.twitch.recompenses.get(cle)
    if rc is None:
        raise HTTPException(404, f"Aucune entrée twitch.recompenses.{cle} dans config.yaml")
    return rc


@admin_router.get("/recompenses")
async def lister(request: Request) -> dict:
    gestion = _gestion(request)
    return {
        "recompenses": await gestion.lister(),
        "prix_dynamique_tts": asdict(request.app.state.wally.config.twitch.prix_dynamique_tts),
        "limites": {"titre_max": TITRE_MAX, "prompt_max": PROMPT_MAX,
                    "recharge_max_s": RECHARGE_MAX_S},
    }


@admin_router.patch("/recompenses/prix-dynamique")
async def modifier_prix_dynamique(request: Request, body: ModifPrixDynamique) -> dict:
    gestion = _gestion(request)
    config = request.app.state.wally.config
    pd = config.twitch.prix_dynamique_tts
    if body.hausse_pct is not None:
        if not 0 <= body.hausse_pct <= 1000:
            raise HTTPException(422, "La hausse par achat va de 0 à 1000 %")
        pd.hausse_pct = float(body.hausse_pct)
    if body.demi_vie_minutes is not None:
        if not 0.5 <= body.demi_vie_minutes <= 1440:
            raise HTTPException(422, "La demi-vie va de 0,5 à 1440 minutes")
        pd.demi_vie_minutes = float(body.demi_vie_minutes)
    config.save()
    prix = await gestion.pousser_prix_tts()
    return {"ok": True, "prix_dynamique_tts": asdict(pd), "prix_courant": prix}


@admin_router.patch("/recompenses/{cle}")
async def modifier(request: Request, cle: str, body: ModifRecompense) -> dict:
    gestion = _gestion(request)
    rc = _conf(request, cle)
    if body.titre is not None:
        titre = body.titre.strip()
        if not titre or len(titre) > TITRE_MAX:
            raise HTTPException(422, f"Le titre fait de 1 à {TITRE_MAX} caractères")
        rc.titre = titre
    if body.cout is not None:
        if body.cout < 1:
            raise HTTPException(422, "Le prix est d'au moins 1 point")
        rc.cout = int(body.cout)
    if body.prompt is not None:
        if len(body.prompt) > PROMPT_MAX:
            raise HTTPException(422, f"L'invite fait au plus {PROMPT_MAX} caractères")
        rc.prompt = body.prompt.strip()
    if body.recharge_s is not None:
        if not 0 <= body.recharge_s <= RECHARGE_MAX_S:
            raise HTTPException(422, "La recharge va de 0 à 604800 secondes (7 jours)")
        rc.recharge_s = int(body.recharge_s)
    request.app.state.wally.config.save()
    if not rc.active:
        return {"ok": True, "en_ligne": False}
    reward_id = await gestion.appliquer(cle)
    if not reward_id:
        raise HTTPException(502, "Réglage rangé, mais Twitch a refusé la mise à jour "
                                 "(voir le Journal)")
    return {"ok": True, "en_ligne": True, "reward_id": reward_id}


@admin_router.delete("/recompenses/{cle}")
async def supprimer(request: Request, cle: str) -> dict:
    gestion = _gestion(request)
    _conf(request, cle)
    if not await gestion.supprimer(cle):
        raise HTTPException(502, "Twitch a refusé la suppression (voir le Journal)")
    return {"ok": True}


@admin_router.post("/recompenses/{cle}/activer")
async def activer(request: Request, cle: str) -> dict:
    gestion = _gestion(request)
    rc = _conf(request, cle)
    rc.active = True
    request.app.state.wally.config.save()
    reward_id = await gestion.appliquer(cle)
    if not reward_id:
        raise HTTPException(502, "Twitch a refusé la création (plafond de 50 "
                                 "récompenses ? voir le Journal)")
    note = ""
    if cle == "duel_apex" and getattr(request.app.state.wally.twitch_bot,
                                      "duel_runner", None) is None:
        note = ("Récompense recréée, mais le duel n'est armé qu'au démarrage : "
                "redémarre le bot, sinon chaque achat sera remboursé.")
    return {"ok": True, "reward_id": reward_id, "note": note}
