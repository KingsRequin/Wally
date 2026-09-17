# bot/dashboard/routes/config_systeme.py
"""Réglages « système » du panel admin : transcription vocale, veille RSS,
salons de service.

Chaque réglage exposé ici a un lecteur nommé (CLAUDE.md, 0bis) ; ce qui n'est
lu qu'au démarrage est dit tel quel à l'écran. Les écritures sont TOUT OU
RIEN : le corps entier est validé avant de toucher à l'objet config, sinon un
422 sur le dernier champ laisserait les premiers modifiés en mémoire sans être
rangés. Les ids Discord voyagent en CHAÎNES (un snowflake dépasse 2^53).
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.config import RSSFeedDef

admin_router = APIRouter()


def _refus(message: str) -> HTTPException:
    return HTTPException(422, message)


def _corps(body: Any) -> dict:
    if not isinstance(body, dict):
        raise _refus("Un objet JSON est attendu")
    return body


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


def _choix(valeur: Any, nom: str, permis: tuple[str, ...]) -> str:
    if valeur not in permis:
        raise _refus(f"{nom} : valeur inconnue « {valeur} »")
    return str(valeur)


def _snowflake(valeur: Any, nom: str) -> str:
    """Un id Discord en chaîne de chiffres, ou `""`."""
    if valeur is None:
        return ""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, int)):
        raise _refus(f"{nom} : un identifiant Discord est attendu")
    texte = str(valeur).strip()
    if texte and not re.fullmatch(r"\d{13,21}", texte):
        raise _refus(f"{nom} : « {texte} » n'est pas un identifiant Discord")
    return texte


def _id_salon(valeur: Any, nom: str) -> int | None:
    texte = _snowflake(valeur, nom)
    return int(texte) if texte else None


def _chaine_id(valeur: int | None) -> str:
    return str(valeur) if valeur else ""


def _appliquer(a_poser: list[tuple[object, str, object]]) -> None:
    for cible, cle, valeur in a_poser:
        setattr(cible, cle, valeur)


# ─── Discord › Voix : transcription et accès ─────────────────────────────────

# Lus par `VoiceService._build_stt_pipeline` et `providers._build_batch_stt`.
MOTEURS_STT = (
    ("remote_stream", "Serveur GPU distant (repli local si injoignable)"),
    ("faster_whisper", "Local sur le CPU (faster-whisper)"),
    ("azure", "Azure Speech"),
)
REPLIS_STT = (
    ("faster_whisper", "Local sur le CPU (faster-whisper)"),
    ("azure", "Azure Speech"),
)
# `build_overflow_stt` ne connaît que xai ; "" = aucune soupape.
SOUPAPES_STT = (("", "Aucune (la parole en trop est jetée)"), ("xai", "xAI (Grok STT)"))
MODELES_WHISPER = ("tiny", "base", "small", "medium", "large-v3")
URL_STT_MAX = 200
# Au-delà d'une dizaine, la VRAM d'une carte grand public ne suit pas.
CONNEXIONS_STT_MAX = 8
SOUPAPE_DELAI_MAX_S = 120.0
SOUPAPE_TARIF_MAX = 10.0
SOUPAPE_EN_VOL_MAX = 32
SILENCE_MIN_S = 0.2
SILENCE_MAX_S = 5.0
DEMANDEURS_MAX = 20
# Les champs de `voice.requesters` et leurs lecteurs : `discord_id` (qui parle,
# `request.resolve_requester`, priorité GPU), `twitch_id` (droits du streamer,
# `droits_du_demandeur`), `twitch_login` (mention, `request.py`), et les trois
# `apex_*` (`core/apex/seed.py` : inscription du compte et uid du duel).
PLATEFORMES_APEX = ("PC", "PS4", "X1")


def _etat_voix(config) -> dict:
    v = config.voice
    return {
        "stt_provider": v.stt_provider,
        "remote_stt_url": v.remote_stt_url,
        "remote_stt_max_connections": v.remote_stt_max_connections,
        "remote_stt_fallback": v.remote_stt_fallback,
        "overflow_stt_provider": v.overflow_stt_provider,
        "overflow_stt_timeout_s": v.overflow_stt_timeout_s,
        "overflow_stt_usd_per_hour": v.overflow_stt_usd_per_hour,
        "overflow_stt_max_inflight": v.overflow_stt_max_inflight,
        "whisper_model": v.whisper_model,
        "vad_silence_timeout_s": v.vad_silence_timeout_s,
        "requesters": [_demandeur_sortant(r) for r in (v.requesters or [])],
        # Une soupape choisie sans clé ne s'ouvre jamais : l'écran le dit.
        "cle_xai_presente": bool(os.environ.get("XAI_API_KEY")),
        "choix": {
            "moteurs": [list(c) for c in MOTEURS_STT],
            "replis": [list(c) for c in REPLIS_STT],
            "soupapes": [list(c) for c in SOUPAPES_STT],
            "modeles_whisper": list(MODELES_WHISPER),
            "plateformes_apex": list(PLATEFORMES_APEX),
        },
    }


def _demandeur_sortant(entree: dict | None) -> dict:
    e = entree or {}
    return {
        "discord_id": str(e.get("discord_id") or ""),
        "twitch_id": str(e.get("twitch_id") or ""),
        "twitch_login": str(e.get("twitch_login") or ""),
        "apex_name": str(e.get("apex_name") or ""),
        "apex_uid": str(e.get("apex_uid") or ""),
        "apex_platform": str(e.get("apex_platform") or ""),
    }


def _demandeurs(brut: Any) -> list[dict]:
    """Valide la liste ; ne range que les champs remplis, comme la config écrite
    à la main (les lecteurs traitent l'absence et le vide pareil)."""
    if not isinstance(brut, list):
        raise _refus("Demandeurs : une liste est attendue")
    if len(brut) > DEMANDEURS_MAX:
        raise _refus(f"Demandeurs : {DEMANDEURS_MAX} au plus")
    sortie: list[dict] = []
    vus: set[str] = set()
    for i, e in enumerate(brut, start=1):
        if not isinstance(e, dict):
            raise _refus(f"Demandeur {i} : un objet est attendu")
        discord_id = _snowflake(e.get("discord_id"), f"Demandeur {i}, id Discord")
        twitch_id = _texte(str(e.get("twitch_id") or ""), f"Demandeur {i}, id Twitch", 20)
        if twitch_id and not twitch_id.isdigit():
            raise _refus(f"Demandeur {i} : l'id Twitch ne contient que des chiffres")
        # Au moins une identité : sans elle, l'entrée ne reconnaît personne.
        if not discord_id and not twitch_id:
            raise _refus(f"Demandeur {i} : un id Discord ou un id Twitch est obligatoire")
        for cle in (f"d{discord_id}" if discord_id else "", f"t{twitch_id}" if twitch_id else ""):
            if cle and cle in vus:
                raise _refus(f"Demandeur {i} : cette identité est déjà dans la liste")
            vus.add(cle)
        login = _texte(e.get("twitch_login") or "", f"Demandeur {i}, pseudo Twitch", 25).lower()
        if login and not re.fullmatch(r"[a-z0-9_]{1,25}", login):
            raise _refus(f"Demandeur {i} : pseudo Twitch invalide « {login} »")
        apex_name = _texte(e.get("apex_name") or "", f"Demandeur {i}, compte Apex", 64)
        apex_uid = _texte(str(e.get("apex_uid") or ""), f"Demandeur {i}, uid Apex", 30)
        if apex_uid and not apex_uid.isdigit():
            raise _refus(f"Demandeur {i} : l'uid Apex ne contient que des chiffres")
        plateforme = e.get("apex_platform") or ""
        if plateforme:
            _choix(plateforme, f"Demandeur {i}, plateforme Apex", PLATEFORMES_APEX)
        propre = {"discord_id": discord_id, "twitch_id": twitch_id, "twitch_login": login,
                  "apex_name": apex_name, "apex_uid": apex_uid, "apex_platform": plateforme}
        sortie.append({k: val for k, val in propre.items() if val})
    return sortie


@admin_router.get("/systeme/voix")
async def lire_voix(request: Request) -> dict:
    return _etat_voix(request.app.state.wally.config)


@admin_router.put("/systeme/voix")
async def ecrire_voix(request: Request) -> dict:
    body = _corps(await request.json())
    config = request.app.state.wally.config
    v = config.voice
    a_poser: list[tuple[object, str, object]] = []
    moteurs = tuple(c[0] for c in MOTEURS_STT)
    if "stt_provider" in body:
        a_poser.append((v, "stt_provider", _choix(body["stt_provider"], "Moteur de transcription", moteurs)))
    if "remote_stt_url" in body:
        url = _texte(body["remote_stt_url"], "Adresse du serveur GPU", URL_STT_MAX)
        if not re.fullmatch(r"wss?://[^\s/]+(/\S*)?", url):
            raise _refus("Adresse du serveur GPU : ws://hôte:port ou wss://… attendu")
        a_poser.append((v, "remote_stt_url", url))
    if "remote_stt_max_connections" in body:
        a_poser.append((v, "remote_stt_max_connections", _entier(
            body["remote_stt_max_connections"], "Places sur le serveur GPU", 1, CONNEXIONS_STT_MAX)))
    if "remote_stt_fallback" in body:
        a_poser.append((v, "remote_stt_fallback", _choix(
            body["remote_stt_fallback"], "Repli du serveur GPU", tuple(c[0] for c in REPLIS_STT))))
    if "overflow_stt_provider" in body:
        a_poser.append((v, "overflow_stt_provider", _choix(
            body["overflow_stt_provider"], "Soupape de débordement", tuple(c[0] for c in SOUPAPES_STT))))
    if "overflow_stt_timeout_s" in body:
        a_poser.append((v, "overflow_stt_timeout_s", _reel(
            body["overflow_stt_timeout_s"], "Délai de la soupape", 1.0, SOUPAPE_DELAI_MAX_S)))
    if "overflow_stt_usd_per_hour" in body:
        a_poser.append((v, "overflow_stt_usd_per_hour", _reel(
            body["overflow_stt_usd_per_hour"], "Tarif de la soupape", 0.0, SOUPAPE_TARIF_MAX)))
    if "overflow_stt_max_inflight" in body:
        a_poser.append((v, "overflow_stt_max_inflight", _entier(
            body["overflow_stt_max_inflight"], "Appels simultanés de la soupape", 1, SOUPAPE_EN_VOL_MAX)))
    if "whisper_model" in body:
        modele = body["whisper_model"]
        # La valeur en place reste acceptée même hors liste (écrite à la main).
        if modele != v.whisper_model:
            _choix(modele, "Modèle local", MODELES_WHISPER)
        a_poser.append((v, "whisper_model", str(modele)))
    if "vad_silence_timeout_s" in body:
        a_poser.append((v, "vad_silence_timeout_s", _reel(
            body["vad_silence_timeout_s"], "Fin de parole", SILENCE_MIN_S, SILENCE_MAX_S)))
    if "requesters" in body:
        a_poser.append((v, "requesters", _demandeurs(body["requesters"])))

    _appliquer(a_poser)
    config.save()
    # Le service vit sur le bot Discord (`setup_hook`). Il reconstruit la chaîne
    # STT tout de suite, sauf le moteur principal pendant une session (appliqué
    # au join suivant) et le délai de fin de parole (figé dans le sink du join).
    service = getattr(request.app.state.wally.discord_bot, "voice_service", None)
    if service is not None:
        service.reload_config(v)
    return _etat_voix(config)


# ─── Système › Veille (RSS) ──────────────────────────────────────────────────

ROLES_FLUX = (("stimulus", "Amorce de pensée"), ("knowledge", "Base de connaissances"))
TYPES_FLUX = (("rss", "Flux RSS ou Atom"), ("steam", "Annonces d'un jeu Steam"))
FLUX_MAX = 40
NOM_FLUX_MAX = 60
URL_FLUX_MAX = 500


def _etat_veille(config) -> dict:
    r = config.rss
    return {
        "enabled": r.enabled,
        "poll_interval_minutes": r.poll_interval_minutes,
        "retention_days": r.retention_days,
        "summary_max_chars": r.summary_max_chars,
        "stimulus_max_age_hours": r.stimulus_max_age_hours,
        "knowledge_max_age_days": r.knowledge_max_age_days,
        "feeds": [asdict(f) for f in r.feeds],
        "choix": {"roles": [list(c) for c in ROLES_FLUX], "types": [list(c) for c in TYPES_FLUX]},
    }


def _flux(brut: Any) -> list[RSSFeedDef]:
    if not isinstance(brut, list):
        raise _refus("Flux : une liste est attendue")
    if len(brut) > FLUX_MAX:
        raise _refus(f"Flux : {FLUX_MAX} au plus")
    sortie: list[RSSFeedDef] = []
    noms: set[str] = set()
    for i, f in enumerate(brut, start=1):
        if not isinstance(f, dict):
            raise _refus(f"Flux {i} : un objet est attendu")
        nom = _texte(f.get("name") or "", f"Flux {i}, nom", NOM_FLUX_MAX)
        if not nom:
            raise _refus(f"Flux {i} : le nom est obligatoire")
        # Le nom est la clé des articles en base (`feed_name`) : deux flux du
        # même nom mélangeraient leurs articles.
        if nom.lower() in noms:
            raise _refus(f"Flux « {nom} » : ce nom est déjà pris")
        noms.add(nom.lower())
        genre = _choix(f.get("kind") or "rss", f"Flux « {nom} », type", tuple(c[0] for c in TYPES_FLUX))
        role = _choix(f.get("role") or "stimulus", f"Flux « {nom} », usage", tuple(c[0] for c in ROLES_FLUX))
        langue = _texte(f.get("lang") or "fr", f"Flux « {nom} », langue", 5).lower()
        if not re.fullmatch(r"[a-z]{2}", langue):
            raise _refus(f"Flux « {nom} » : langue sur deux lettres (fr, en…)")
        actif = _booleen(f.get("enabled", True), f"Flux « {nom} », actif")
        url = _texte(f.get("url") or "", f"Flux « {nom} », adresse", URL_FLUX_MAX)
        appid = _texte(f.get("appid") or "", f"Flux « {nom} », appid Steam", 12)
        if genre == "rss":
            if not re.fullmatch(r"https?://\S+", url):
                raise _refus(f"Flux « {nom} » : adresse http(s) obligatoire")
            appid = ""
        else:
            if not appid.isdigit():
                raise _refus(f"Flux « {nom} » : l'appid Steam est un nombre")
            url = ""
        sortie.append(RSSFeedDef(name=nom, url=url, role=role, lang=langue,
                                 enabled=actif, kind=genre, appid=appid))
    return sortie


@admin_router.get("/systeme/veille")
async def lire_veille(request: Request) -> dict:
    return _etat_veille(request.app.state.wally.config)


@admin_router.put("/systeme/veille")
async def ecrire_veille(request: Request) -> dict:
    body = _corps(await request.json())
    config = request.app.state.wally.config
    r = config.rss
    a_poser: list[tuple[object, str, object]] = []
    if "enabled" in body:
        a_poser.append((r, "enabled", _booleen(body["enabled"], "Veille active")))
    if "poll_interval_minutes" in body:
        a_poser.append((r, "poll_interval_minutes",
                        _entier(body["poll_interval_minutes"], "Relevé des flux", 5, 1440)))
    if "retention_days" in body:
        a_poser.append((r, "retention_days", _entier(body["retention_days"], "Conservation", 1, 365)))
    if "summary_max_chars" in body:
        a_poser.append((r, "summary_max_chars",
                        _entier(body["summary_max_chars"], "Longueur des résumés", 50, 2000)))
    if "stimulus_max_age_hours" in body:
        a_poser.append((r, "stimulus_max_age_hours",
                        _entier(body["stimulus_max_age_hours"], "Fraîcheur des amorces", 1, 720)))
    if "knowledge_max_age_days" in body:
        a_poser.append((r, "knowledge_max_age_days",
                        _entier(body["knowledge_max_age_days"], "Fraîcheur des connaissances", 1, 3650)))
    if "feeds" in body:
        a_poser.append((r, "feeds", _flux(body["feeds"])))
    _appliquer(a_poser)
    config.save()
    return _etat_veille(config)


# ─── Système › Connexions : salons de service et chat web ────────────────────

COOLDOWN_CHAT_WEB_MAX_S = 3600


def _etat_salons(config) -> dict:
    return {
        "web_chat_cooldown_seconds": config.web_chat.cooldown_seconds,
        "journal_channel_id": _chaine_id(config.bot.journal_channel_id),
        "bedroom_channel_id": _chaine_id(config.bot.bedroom_channel_id),
        "stream_voice_channel_id": _chaine_id(config.bot.stream_voice_channel_id),
    }


@admin_router.get("/systeme/salons-service")
async def lire_salons(request: Request) -> dict:
    return _etat_salons(request.app.state.wally.config)


@admin_router.put("/systeme/salons-service")
async def ecrire_salons(request: Request) -> dict:
    body = _corps(await request.json())
    etat = request.app.state.wally
    config = etat.config
    a_poser: list[tuple[object, str, object]] = []
    if "web_chat_cooldown_seconds" in body:
        a_poser.append((config.web_chat, "cooldown_seconds", _entier(
            body["web_chat_cooldown_seconds"], "Délai du chat web", 0, COOLDOWN_CHAT_WEB_MAX_S)))
    for cle, nom in (("journal_channel_id", "Salon du journal"),
                     ("bedroom_channel_id", "Chambre de Wally"),
                     ("stream_voice_channel_id", "Salon vocal du live")):
        if cle in body:
            a_poser.append((config.bot, cle, _id_salon(body[cle], nom)))

    vocal_avant = config.bot.stream_voice_channel_id
    chambre_avant = config.bot.bedroom_channel_id
    _appliquer(a_poser)
    config.save()

    discord_bot = etat.discord_bot
    if config.bot.bedroom_channel_id != chambre_avant:
        boucle = getattr(discord_bot, "cognitive_loop", None)
        if boucle is not None:
            boucle.poser_chambre(config.bot.bedroom_channel_id)
    if config.bot.stream_voice_channel_id != vocal_avant:
        # Le dernier salon de live rejoint est retenu en base et PASSE DEVANT la
        # config (`resolve_voice_channel_id`) : sans cet oubli, changer le salon
        # ici n'aurait rien changé au prochain live.
        from bot.discord.voice.channel_memory import forget_voice_channel

        await forget_voice_channel(etat.db)
        logger.info("Salon vocal du live changé ({a} → {b}) : dernier salon retenu oublié",
                    a=vocal_avant, b=config.bot.stream_voice_channel_id)
    return _etat_salons(config)
