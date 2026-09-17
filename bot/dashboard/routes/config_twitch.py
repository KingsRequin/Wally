# bot/dashboard/routes/config_twitch.py
"""Réglages « twitch » du panel admin : Chat & événements, Apex.

Chaque réglage exposé ici a un lecteur nommé (cf. CLAUDE.md, 0bis). Ce qui est
relu à chaque usage est dit « à chaud » ; ce qui n'est lu qu'au boot
(`bot/main.py`) est dit tel quel à l'écran — `a_chaud` dans les réponses.

Les écritures sont TOUT OU RIEN : on valide l'ensemble du corps avant de
toucher à l'objet config, sinon un 422 sur le dernier champ laisserait les
premiers modifiés en mémoire sans être rangés.
"""
from __future__ import annotations

import string
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from bot.config import TwitchEventConfig
from bot.core.apex.duel_runner import PLAFOND_MARGE_LOBBY_S

admin_router = APIRouter()


# ─── Chat & événements ────────────────────────────────────────────────────────

# Les variables que `bot/twitch/events/social.py` passe RÉELLEMENT à chaque
# gabarit, et qui y ont un sens (`months` vaut 0 sur un follow : il est passé,
# mais l'autoriser n'y écrirait qu'un zéro). Un nom hors de cette liste serait
# laissé tel quel dans le message par `format_event_message` : on le refuse à
# la saisie plutôt que de le découvrir dans le chat.
EVENEMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "follow": ("Follow", ("username",)),
    "sub": ("Abonnement", ("username",)),
    "resub": ("Réabonnement", ("username", "months")),
    "gift_sub": ("Abonnements offerts", ("username", "amount")),
    "bits": ("Bits", ("username", "amount")),
    "raid": ("Raid", ("username", "raiders_count", "contexte")),
}

MESSAGE_MAX = 500
COOLDOWN_MAX_S = 3600
ATTENTE_MAX_S = 60.0
CADENCE_ANNONCES_MIN = 5
CADENCE_ANNONCES_MAX = 240


def _refus(message: str) -> HTTPException:
    return HTTPException(422, message)


def _entier(valeur: Any, nom: str, mini: int, maxi: int) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or int(valeur) != valeur:
        raise _refus(f"{nom} : un nombre entier est attendu")
    if not mini <= valeur <= maxi:
        raise _refus(f"{nom} : entre {mini} et {maxi}")
    return int(valeur)


def _reel(valeur: Any, nom: str, mini: float, maxi: float) -> float:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise _refus(f"{nom} : un nombre est attendu")
    if not mini <= valeur <= maxi:
        raise _refus(f"{nom} : entre {mini:g} et {maxi:g}")
    return float(valeur)


def _booleen(valeur: Any, nom: str) -> bool:
    if not isinstance(valeur, bool):
        raise _refus(f"{nom} : vrai ou faux attendu")
    return valeur


def _texte(valeur: Any, nom: str, maxi: int) -> str:
    if not isinstance(valeur, str):
        raise _refus(f"{nom} : un texte est attendu")
    valeur = valeur.strip()
    if len(valeur) > maxi:
        raise _refus(f"{nom} : {maxi} caractères au plus")
    return valeur


def _gabarit(cle: str, message: str) -> None:
    """Refuse un gabarit que `format_event_message` ne saurait pas remplir."""
    libelle, permises = EVENEMENTS[cle]
    try:
        champs = [nom for _, nom, _, _ in string.Formatter().parse(message) if nom is not None]
    except ValueError:
        raise _refus(f"{libelle} : accolade non fermée dans le message "
                     "(écrire {{ ou }} pour une accolade littérale)") from None
    for nom in champs:
        if nom not in permises:
            dispo = ", ".join("{" + p + "}" for p in permises)
            raise _refus(f"{libelle} : variable inconnue {{{nom}}} — disponibles : {dispo}")


def _etat_chat(config) -> dict:
    tw = config.twitch
    evenements = []
    for cle, (libelle, variables) in EVENEMENTS.items():
        ev = config.twitch_events.get(cle)
        evenements.append({
            "cle": cle, "libelle": libelle, "variables": list(variables),
            "active": bool(ev.active) if ev else False,
            "message": ev.message if ev else "",
        })
    return {
        "evenements": evenements,
        "cooldown_seconds": tw.cooldown_seconds,
        "attente_seuil_s": tw.attente_seuil_s,
        "shoutout_raid": tw.shoutout_raid,
        "annonces_auto": asdict(tw.annonces_auto),
        "bornes": {
            "message_max": MESSAGE_MAX,
            "cooldown_max_s": COOLDOWN_MAX_S,
            "attente_max_s": ATTENTE_MAX_S,
            "cadence_annonces_min": CADENCE_ANNONCES_MIN,
            "cadence_annonces_max": CADENCE_ANNONCES_MAX,
        },
    }


@admin_router.get("/twitch/chat")
async def lire_chat(request: Request) -> dict:
    return _etat_chat(request.app.state.wally.config)


@admin_router.patch("/twitch/chat")
async def modifier_chat(request: Request, body: dict) -> dict:
    config = request.app.state.wally.config
    tw = config.twitch
    a_poser: list = []  # (objet, attribut, valeur) — posés seulement si TOUT est valide

    evs = body.get("evenements")
    if evs is not None:
        if not isinstance(evs, dict):
            raise _refus("evenements : un objet {clé: {active, message}} est attendu")
        for cle, champs in evs.items():
            if cle not in EVENEMENTS:
                raise _refus(f"Événement inconnu : {cle}")
            if not isinstance(champs, dict):
                raise _refus(f"{cle} : un objet {{active, message}} est attendu")
            libelle = EVENEMENTS[cle][0]
            actuel = config.twitch_events.get(cle)
            active = (_booleen(champs["active"], libelle) if "active" in champs
                      else bool(actuel.active) if actuel else False)
            message = (_texte(champs["message"], libelle, MESSAGE_MAX) if "message" in champs
                       else actuel.message if actuel else "")
            _gabarit(cle, message)
            if active and not message:
                raise _refus(f"{libelle} : un message activé ne peut pas être vide")
            a_poser.append((config.twitch_events, cle, TwitchEventConfig(active=active, message=message)))

    if "cooldown_seconds" in body:
        a_poser.append((tw, "cooldown_seconds",
                        _entier(body["cooldown_seconds"], "Délai entre deux réponses", 0, COOLDOWN_MAX_S)))
    if "attente_seuil_s" in body:
        a_poser.append((tw, "attente_seuil_s",
                        _reel(body["attente_seuil_s"], "Seuil du message d'attente", 0, ATTENTE_MAX_S)))
    if "shoutout_raid" in body:
        a_poser.append((tw, "shoutout_raid", _booleen(body["shoutout_raid"], "Shoutout au raid")))
    aa = body.get("annonces_auto")
    if aa is not None:
        if not isinstance(aa, dict):
            raise _refus("annonces_auto : un objet {active, cadence_minutes} est attendu")
        if "active" in aa:
            a_poser.append((tw.annonces_auto, "active", _booleen(aa["active"], "Rappels automatiques")))
        if "cadence_minutes" in aa:
            a_poser.append((tw.annonces_auto, "cadence_minutes",
                            _entier(aa["cadence_minutes"], "Cadence des rappels",
                                    CADENCE_ANNONCES_MIN, CADENCE_ANNONCES_MAX)))

    for cible, cle, valeur in a_poser:
        if isinstance(cible, dict):
            cible[cle] = valeur
        else:
            setattr(cible, cle, valeur)
    config.save()
    return _etat_chat(config)


# ─── Apex ─────────────────────────────────────────────────────────────────────

PLATEFORMES = (("PC", "PC"), ("PS4", "PlayStation"), ("X1", "Xbox"))
COMPTE_MAX = 64
MODE_JEU_MAX = 60
MANCHES_MAX = 10
CADENCE_DUEL_MIN_S = 1.0
CADENCE_DUEL_MAX_S = 15.0
ATTENTE_SQUAD_MAX_MIN = 60.0
# Un ORDRE DE GRANDEUR, pas une limite serrée : à 30, il a jeté 39 kills réels
# le 2026-08-13 (cf. `DuelConfig.plafond_kills_manche`). D'où un plancher.
PLAFOND_KILLS_MIN = 50
PLAFOND_KILLS_MAX = 100000
API_MUETTE_MIN_S = 30.0
API_MUETTE_MAX_S = 1800.0


def _etat_apex(config) -> dict:
    apex = config.apex
    return {
        "streamer_account": apex.streamer_account,
        "streamer_platform": apex.streamer_platform,
        "duel": asdict(apex.duel),
        "plateformes": [list(p) for p in PLATEFORMES],
        "bornes": {
            "compte_max": COMPTE_MAX,
            "mode_jeu_max": MODE_JEU_MAX,
            "manches_max": MANCHES_MAX,
            "cadence_min_s": CADENCE_DUEL_MIN_S,
            "cadence_max_s": CADENCE_DUEL_MAX_S,
            "attente_squad_max_min": ATTENTE_SQUAD_MAX_MIN,
            "plafond_kills_min": PLAFOND_KILLS_MIN,
            "plafond_kills_max": PLAFOND_KILLS_MAX,
            "plafond_marge_lobby_s": PLAFOND_MARGE_LOBBY_S,
            "api_muette_min_s": API_MUETTE_MIN_S,
            "api_muette_max_s": API_MUETTE_MAX_S,
        },
    }


@admin_router.get("/apex/reglages")
async def lire_apex(request: Request) -> dict:
    return _etat_apex(request.app.state.wally.config)


@admin_router.patch("/apex/reglages")
async def modifier_apex(request: Request, body: dict) -> dict:
    config = request.app.state.wally.config
    apex = config.apex
    duel = apex.duel
    a_poser: list = []

    if "streamer_account" in body:
        a_poser.append((apex, "streamer_account",
                        _texte(body["streamer_account"], "Compte Apex du streamer", COMPTE_MAX)))
    if "streamer_platform" in body:
        plateforme = body["streamer_platform"]
        if plateforme not in {p[0] for p in PLATEFORMES}:
            raise _refus("Plateforme : PC, PS4 ou X1")
        a_poser.append((apex, "streamer_platform", plateforme))

    d = body.get("duel")
    if d is not None:
        if not isinstance(d, dict):
            raise _refus("duel : un objet est attendu")
        if "active" in d:
            a_poser.append((duel, "active", _booleen(d["active"], "Duel activé")))
        if "manches" in d:
            a_poser.append((duel, "manches", _entier(d["manches"], "Manches", 1, MANCHES_MAX)))
        if "cadence_s" in d:
            a_poser.append((duel, "cadence_s", _reel(d["cadence_s"], "Cadence de sonde",
                                                     CADENCE_DUEL_MIN_S, CADENCE_DUEL_MAX_S)))
        if "attente_squad_min" in d:
            a_poser.append((duel, "attente_squad_min",
                            _reel(d["attente_squad_min"], "Attente de l'escouade", 1, ATTENTE_SQUAD_MAX_MIN)))
        if "plafond_kills_manche" in d:
            a_poser.append((duel, "plafond_kills_manche",
                            _entier(d["plafond_kills_manche"], "Plafond de kills par manche",
                                    PLAFOND_KILLS_MIN, PLAFOND_KILLS_MAX)))
        if "marge_lobby_s" in d:
            a_poser.append((duel, "marge_lobby_s",
                            _reel(d["marge_lobby_s"], "Marge au lobby", 0, PLAFOND_MARGE_LOBBY_S)))
        if "mode_jeu" in d:
            a_poser.append((duel, "mode_jeu", _texte(d["mode_jeu"], "Mode de jeu", MODE_JEU_MAX)))
        if "api_muette_max_s" in d:
            a_poser.append((duel, "api_muette_max_s",
                            _reel(d["api_muette_max_s"], "Silence de l'API toléré",
                                  API_MUETTE_MIN_S, API_MUETTE_MAX_S)))

    # Le budget de 39 s entre un retour au lobby et la partie suivante : le
    # debounce consomme deux relevés AVANT la marge (`marge_lobby_bornee`). Le
    # runner bornerait en silence côté log ; ici, on le dit à qui règle.
    futur = {c: v for o, c, v in a_poser if o is duel}
    cadence = futur.get("cadence_s", duel.cadence_s)
    marge = futur.get("marge_lobby_s", duel.marge_lobby_s)
    if 2 * float(cadence) + float(marge) > PLAFOND_MARGE_LOBBY_S:
        raise _refus(
            f"Marge au lobby + deux relevés ({marge:g} + 2 × {cadence:g} s) dépasse "
            f"les {PLAFOND_MARGE_LOBBY_S:g} s entre un retour au lobby et la partie "
            "suivante : une manche mordrait sur la suivante")

    for cible, cle, valeur in a_poser:
        setattr(cible, cle, valeur)
    config.save()
    return _etat_apex(config)
