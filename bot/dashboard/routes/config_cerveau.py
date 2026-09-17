# bot/dashboard/routes/config_cerveau.py
"""Réglages « cerveau » du panel admin : rythmes émotionnels, prise de parole,
mémoire, modèles de la cognition, images spontanées.

Chaque réglage exposé ici a un LECTEUR nommé dans son commentaire. Ce qui est
relu à chaque usage (`bot.config.…` lu au moment de servir) s'applique à chaud ;
ce qui est capturé à la construction d'un service est soit poussé dans le
service vivant, soit annoncé « au prochain redémarrage » dans la réponse — le
panel ne promet jamais « à chaud » ce qu'aucune ligne ne relit.

Chaque écriture VALIDE tout le corps avant de toucher à l'objet config : une
erreur sur le dernier champ ne laisse aucune mutation à moitié faite.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from bot.core.emotion import EMOTIONS
from bot.core.llm import SUPPORTED_TEXT_PROVIDERS

admin_router = APIRouter()

_MODELE_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
# Le repli de `bootstrap.py` quand `openai.vision_model` est vide.
_VISION_DEFAUT = "gpt-5-nano"


# ── Validation ──────────────────────────────────────────────────────────────

def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _dict(valeur: object, libelle: str) -> dict:
    if not isinstance(valeur, dict):
        raise _refus(f"{libelle} : un objet est attendu.")
    return valeur


def _booleen(valeur: object, libelle: str) -> bool:
    if not isinstance(valeur, bool):
        raise _refus(f"{libelle} : oui ou non attendu.")
    return valeur


def _nombre(valeur: object, libelle: str, mini: float, maxi: float) -> float:
    # `bool` est un `int` en Python : « true » passerait pour 1.
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise _refus(f"{libelle} : un nombre est attendu.")
    if not (mini <= valeur <= maxi):
        raise _refus(f"{libelle} : doit être compris entre {mini:g} et {maxi:g}.")
    return float(valeur)


def _entier(valeur: object, libelle: str, mini: int, maxi: int) -> int:
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise _refus(f"{libelle} : un nombre entier est attendu.")
    if not (mini <= valeur <= maxi):
        raise _refus(f"{libelle} : doit être compris entre {mini} et {maxi}.")
    return valeur


def _modele(valeur: object, libelle: str) -> str:
    if not isinstance(valeur, str) or not _MODELE_RE.match(valeur.strip()):
        raise _refus(f"{libelle} : nom de modèle invalide.")
    return valeur.strip()


def _fournisseur(valeur: object, libelle: str) -> str:
    if valeur not in SUPPORTED_TEXT_PROVIDERS:
        raise _refus(f"{libelle} : fournisseur inconnu (possibles : "
                     f"{', '.join(SUPPORTED_TEXT_PROVIDERS)}).")
    return str(valeur)


def _emotion(valeur: object, libelle: str) -> str:
    if valeur not in EMOTIONS:
        raise _refus(f"{libelle} : émotion inconnue.")
    return str(valeur)


def _emotions(valeur: object, libelle: str) -> list[str]:
    if not isinstance(valeur, list):
        raise _refus(f"{libelle} : une liste d'émotions est attendue.")
    return list(dict.fromkeys(_emotion(e, libelle) for e in valeur))


def _lire(corps: dict, schema: dict[str, tuple]) -> dict[str, Any]:
    """Valide les clés PRÉSENTES de `corps` selon `schema` ; refuse les inconnues.

    `schema[clé] = (fonction, libellé, *bornes)`.
    """
    inconnues = set(corps) - set(schema)
    if inconnues:
        raise _refus(f"Réglage inconnu : {', '.join(sorted(inconnues))}.")
    return {cle: schema[cle][0](corps[cle], *schema[cle][1:])
            for cle in schema if cle in corps}


def _wally(request: Request):
    return request.app.state.wally


# ── 1. Rythmes et prise de parole ───────────────────────────────────────────

# Lecteurs : `discord/handlers.py` et `twitch/handlers.py` relisent
# `bot.config.bot.*` à chaque message → à chaud. Sauf
# `spontaneous_channel_speak_enabled`, capturé par `ReasoningAgent` (sa consigne
# de prompt) et `CognitiveLoop` à leur construction → au redémarrage.
_PAROLE = {
    "spontaneous_discord_enabled": (_booleen, "Intervenir sur Discord"),
    "spontaneous_twitch_enabled": (_booleen, "Intervenir sur Twitch"),
    "spontaneous_channel_speak_enabled": (_booleen, "Pensées publiées d'elles-mêmes"),
    "spontaneous_probability": (_nombre, "Probabilité d'intervenir", 0, 1),
    "spontaneous_passion_probability": (_nombre, "Probabilité sur un sujet qui le passionne", 0, 1),
    "spontaneous_cooldown_seconds": (_entier, "Délai entre deux interventions", 0, 86400),
    "unanswered_question_enabled": (_booleen, "Relever les questions sans réponse"),
    "unanswered_question_delay_seconds": (_entier, "Délai laissé au chat", 5, 3600),
    "unanswered_question_forget_seconds": (_entier, "Oubli d'une question", 10, 86400),
}
_PAROLE_REDEMARRAGE = {"spontaneous_channel_speak_enabled"}

# Lecteur : `core/emotion.py` (`apply_delta`, `_check_fatigue_trigger`), relu à
# chaque delta → à chaud.
_EMOTIONS_BOT = {
    "emotion_inertia_factor": (_nombre, "Inertie", 0, 1),
    "emotion_peak_threshold": (_nombre, "Seuil d'un pic", 0.3, 1),
}
_HUMEUR = {
    "alpha": (_nombre, "Humeur : vitesse d'imprégnation", 0, 1),
    "decay_lambda": (_nombre, "Humeur : vitesse d'effacement", 0, 10),
    "bias_factor": (_nombre, "Humeur : influence sur les émotions", 0, 2),
}
_FATIGUE = {
    "dampening": (_nombre, "Fatigue : amortissement", 0, 1),
    "recovery_rate": (_nombre, "Fatigue : récupération par heure", 0, 10),
}
_HABITUATION = {
    "threshold_count": (_entier, "Lassitude : répétitions tolérées", 1, 50),
    "window_seconds": (_entier, "Lassitude : fenêtre", 10, 86400),
    "decay_factor": (_nombre, "Lassitude : atténuation", 0, 1),
    "reset_seconds": (_entier, "Lassitude : remise à zéro", 60, 86400),
    "exempt": (_emotions, "Lassitude : émotions exemptées"),
}


@admin_router.get("/cerveau/rythmes")
async def lire_rythmes(request: Request) -> dict:
    cfg = _wally(request).config
    return {
        "parole": {cle: getattr(cfg.bot, cle) for cle in _PAROLE},
        "emotions": {cle: getattr(cfg.bot, cle) for cle in _EMOTIONS_BOT},
        "mood": asdict(cfg.mood),
        "fatigue": asdict(cfg.fatigue),
        "habituation": asdict(cfg.habituation),
        "circadian": asdict(cfg.circadian),
        "aftermath": asdict(cfg.aftermath),
        "world_events": {k: asdict(v) for k, v in cfg.world_events.items()},
        "secondaries": {k: asdict(v) for k, v in cfg.secondaries.items()},
    }


@admin_router.put("/cerveau/parole")
async def ecrire_parole(request: Request, body: dict) -> dict:
    state = _wally(request)
    valeurs = _lire(_dict(body, "Prise de parole"), _PAROLE)
    bot = state.config.bot
    delai = valeurs.get("unanswered_question_delay_seconds", bot.unanswered_question_delay_seconds)
    oubli = valeurs.get("unanswered_question_forget_seconds", bot.unanswered_question_forget_seconds)
    if oubli <= delai:
        raise _refus("L'oubli d'une question doit venir après le délai laissé au chat.")
    for cle, valeur in valeurs.items():
        setattr(bot, cle, valeur)
    state.config.save()
    redemarrage = sorted(set(valeurs) & _PAROLE_REDEMARRAGE)
    return {"status": "saved", "au_redemarrage": [_PAROLE[c][1] for c in redemarrage]}


@admin_router.put("/cerveau/emotions")
async def ecrire_emotions(request: Request, body: dict) -> dict:
    """Inertie, seuil de pic, humeur, fatigue, lassitude — tous relus à chaud
    par `EmotionEngine` (`getattr(self._config, …)` à chaque delta ou tick)."""
    state = _wally(request)
    cfg = state.config
    corps = _dict(body, "Émotions")
    sections: dict[str, dict[str, tuple]] = {
        "mood": _HUMEUR, "fatigue": _FATIGUE, "habituation": _HABITUATION}
    inconnues = set(corps) - set(_EMOTIONS_BOT) - set(sections)
    if inconnues:
        raise _refus(f"Réglage inconnu : {', '.join(sorted(inconnues))}.")
    racine = _lire({k: v for k, v in corps.items() if k in _EMOTIONS_BOT}, _EMOTIONS_BOT)
    par_section = {nom: _lire(_dict(corps[nom], nom), schema)
                   for nom, schema in sections.items() if nom in corps}
    for cle, valeur in racine.items():
        setattr(cfg.bot, cle, valeur)
    for nom, valeurs in par_section.items():
        cible = getattr(cfg, nom)
        for cle, valeur in valeurs.items():
            setattr(cible, cle, valeur)
    cfg.save()
    return {"status": "saved", "au_redemarrage": []}


@admin_router.put("/cerveau/circadien")
async def ecrire_circadien(request: Request, body: dict) -> dict:
    """Périodes de la journée. Lecteur : `EmotionEngine._apply_circadian`, à
    chaque delta. Les NOMS de périodes ne se créent ni ne se retirent ici : on
    règle leurs heures et leurs multiplicateurs, la forme reste celle du YAML."""
    state = _wally(request)
    circ = state.config.circadian
    corps = _dict(body, "Rythme de la journée")
    inconnues = set(corps) - {"enabled", "periods"}
    if inconnues:
        raise _refus(f"Réglage inconnu : {', '.join(sorted(inconnues))}.")
    actif = _booleen(corps["enabled"], "Rythme de la journée") if "enabled" in corps else circ.enabled
    nouvelles: dict[str, dict] = {}
    for nom, brut in _dict(corps.get("periods", {}), "Périodes").items():
        if nom not in circ.periods:
            raise _refus(f"Période inconnue : {nom}.")
        p = _dict(brut, nom)
        heures = p.get("hours", circ.periods[nom].hours)
        if not isinstance(heures, list) or len(heures) != 2:
            raise _refus(f"{nom} : une heure de début et une heure de fin sont attendues.")
        debut = _entier(heures[0], f"{nom} : début", 0, 23)
        fin = _entier(heures[1], f"{nom} : fin", 1, 24)
        if fin <= debut:
            raise _refus(f"{nom} : la fin doit venir après le début.")
        valeurs: dict[str, Any] = {"hours": [debut, fin]}
        for e in EMOTIONS:
            if e in p:
                valeurs[e] = _nombre(p[e], f"{nom} : multiplicateur {e}", 0, 3)
        inconnus = set(p) - {"hours"} - set(EMOTIONS)
        if inconnus:
            raise _refus(f"{nom} : champ inconnu {', '.join(sorted(inconnus))}.")
        nouvelles[nom] = valeurs
    # Chevauchement : `_apply_circadian` prend la PREMIÈRE période qui contient
    # l'heure, l'autre serait ignorée en silence sur la plage commune.
    plages = sorted(
        (nouvelles.get(n, {}).get("hours", p.hours), n) for n, p in circ.periods.items())
    for (h1, n1), (h2, n2) in zip(plages, plages[1:], strict=False):
        if h2[0] < h1[1]:
            raise _refus(f"Les périodes {n1} et {n2} se chevauchent.")
    circ.enabled = actif
    for nom, valeurs in nouvelles.items():
        for cle, valeur in valeurs.items():
            setattr(circ.periods[nom], cle, valeur)
    state.config.save()
    return {"status": "saved", "au_redemarrage": []}


@admin_router.put("/cerveau/contrecoup")
async def ecrire_contrecoup(request: Request, body: dict) -> dict:
    """Règles de contrecoup. Lecteur : `EmotionEngine._apply_aftermath`, à
    chaque tick. L'ennui n'est pas une source possible : `_apply_decay` ne
    compte aucune « perte » pour lui (il monte, il ne décroît pas)."""
    state = _wally(request)
    after = state.config.aftermath
    corps = _dict(body, "Contrecoup")
    inconnues = set(corps) - {"enabled", "rules"}
    if inconnues:
        raise _refus(f"Réglage inconnu : {', '.join(sorted(inconnues))}.")
    actif = _booleen(corps["enabled"], "Contrecoup") if "enabled" in corps else after.enabled
    schema = {
        "source": (_emotion, "Émotion qui retombe"),
        "target": (_emotion, "Émotion nourrie"),
        "ratio": (_nombre, "Part convertie", 0, 1),
        "min_peak": (_nombre, "Pic minimal", 0, 1),
        "reset_below": (_nombre, "Fin de l'épisode", 0, 1),
    }
    nouvelles: dict[str, dict] = {}
    for nom, brut in _dict(corps.get("rules", {}), "Règles").items():
        if nom not in after.rules:
            raise _refus(f"Règle inconnue : {nom}.")
        valeurs = _lire(_dict(brut, nom), schema)
        regle = after.rules[nom]
        source = valeurs.get("source", regle.source)
        if source == "boredom":
            raise _refus(f"{nom} : l'ennui ne retombe pas, il ne peut pas être la source.")
        if source == valeurs.get("target", regle.target):
            raise _refus(f"{nom} : une émotion ne peut pas se nourrir d'elle-même.")
        if valeurs.get("reset_below", regle.reset_below) >= valeurs.get("min_peak", regle.min_peak):
            raise _refus(f"{nom} : la fin de l'épisode doit être sous le pic minimal.")
        nouvelles[nom] = valeurs
    after.enabled = actif
    for nom, valeurs in nouvelles.items():
        for cle, valeur in valeurs.items():
            setattr(after.rules[nom], cle, valeur)
    state.config.save()
    return {"status": "saved", "au_redemarrage": []}


@admin_router.put("/cerveau/evenements")
async def ecrire_evenements(request: Request, body: dict) -> dict:
    """Effets des événements du monde. Lecteur : `EmotionEngine.world_event`,
    à chaque déclenchement. Les noms sont ceux que le code appelle
    (`stream_ended`, `left_alone_in_voice`, `ignored`) : on n'en crée pas."""
    state = _wally(request)
    events = state.config.world_events
    nouveaux: dict[str, dict[str, float]] = {}
    for nom, brut in _dict(body, "Événements").items():
        if nom not in events:
            raise _refus(f"Événement inconnu : {nom}.")
        effets = _dict(_dict(brut, nom).get("effects", {}), nom)
        propres: dict[str, float] = {}
        for emotion, delta in effets.items():
            _emotion(emotion, nom)
            valeur = _nombre(delta, f"{nom} : effet sur {emotion}", -1, 1)
            if valeur:
                propres[emotion] = valeur
        nouveaux[nom] = propres
    for nom, effets_ in nouveaux.items():
        events[nom].effects = effets_
    state.config.save()
    return {"status": "saved", "au_redemarrage": []}


@admin_router.put("/cerveau/secondaires")
async def ecrire_secondaires(request: Request, body: dict) -> dict:
    """Seuils des émotions mêlées. Lecteur : `EmotionEngine.get_secondary_emotions`,
    à chaque prompt. Plancher 0.4 : `prompts.py` n'injecte une secondaire qu'à
    partir de cette intensité, un seuil plus bas n'aurait aucun effet visible.
    Un seuil double (une valeur par émotion) reste double."""
    state = _wally(request)
    sec = state.config.secondaries
    nouveaux: dict[str, float | list[float]] = {}
    for nom, brut in _dict(body, "Émotions mêlées").items():
        if nom not in sec:
            raise _refus(f"Émotion mêlée inconnue : {nom}.")
        seuil = _dict(brut, nom).get("threshold")
        if isinstance(sec[nom].threshold, list):
            if not isinstance(seuil, list) or len(seuil) != 2:
                raise _refus(f"{nom} : deux seuils sont attendus.")
            nouveaux[nom] = [_nombre(s, f"{nom} : seuil", 0.4, 1) for s in seuil]
        else:
            nouveaux[nom] = _nombre(seuil, f"{nom} : seuil", 0.4, 1)
    for nom, seuil_ in nouveaux.items():
        sec[nom].threshold = seuil_
    state.config.save()
    return {"status": "saved", "au_redemarrage": []}


# ── 2. Mémoire ──────────────────────────────────────────────────────────────

# Lecteurs, tous relus à chaque usage :
#   memory_context_max_tokens → handlers Discord/Twitch (budget du bloc mémoire)
#   context_token_threshold   → MemoryService.get_context_summarized_if_needed
#   prelude_window_size       → MemoryService.append_prelude + handlers Discord
#   link_min_confidence       → routes/links.py (analyse des liens de comptes)
_MEMOIRE = {
    "memory_context_max_tokens": (_entier, "Budget des souvenirs", 100, 8000),
    "context_token_threshold": (_entier, "Seuil de résumé de la conversation", 500, 32000),
    "prelude_window_size": (_entier, "Messages de prélude", 1, 100),
    "link_min_confidence": (_nombre, "Confiance minimale d'un lien de comptes", 0.5, 1),
}


@admin_router.get("/cerveau/memoire")
async def lire_memoire(request: Request) -> dict:
    bot = _wally(request).config.bot
    return {cle: getattr(bot, cle) for cle in _MEMOIRE}


@admin_router.put("/cerveau/memoire")
async def ecrire_memoire(request: Request, body: dict) -> dict:
    state = _wally(request)
    for cle, valeur in _lire(_dict(body, "Mémoire"), _MEMOIRE).items():
        setattr(state.config.bot, cle, valeur)
    state.config.save()
    return {"status": "saved", "au_redemarrage": []}


# ── 3. Cognition, vision, recherche web ─────────────────────────────────────

def _temperature_lue(role) -> bool:
    """La température part-elle vraiment à l'API pour ce rôle ?

    OpenAI : ignorée par les modèles servis par la Responses API (o1/o3/o4/gpt-5).
    DeepSeek : omise quand la réflexion est activée (`DeepSeekLLMClient._api_params`).
    """
    if role.provider == "openai":
        from bot.core.llm.openai_client import _uses_responses_api
        return not _uses_responses_api(role.model)
    return role.thinking_type != "enabled"


def _clients_cognition(state) -> list[tuple[object, str]]:
    """Les porteurs vivants d'un client de cognition : `(objet, attribut)`.

    Construits dans `WallyDiscord.setup_hook` : le raisonnement et le
    gestionnaire de persona ont chacun leur client. Vide si la cognition ne
    tourne pas (désactivée, ou Discord pas démarré).
    """
    boucle = getattr(state.discord_bot, "cognitive_loop", None)
    raisonnement = getattr(boucle, "_reasoning", None)
    persona = getattr(getattr(boucle, "_dispatcher", None), "_persona", None)
    return [(o, "_llm") for o in (raisonnement, persona) if getattr(o, "_llm", None) is not None]


def _pousser_client(porteurs, fournisseur_avant: str, role, db) -> bool:
    """Même fournisseur : on change le modèle du client en place. Sinon on en
    construit un neuf. Rend True si au moins un client vivant a été mis à jour."""
    from bot.core.llm import create_llm_client
    for objet, attribut in porteurs:
        if role.provider == fournisseur_avant:
            getattr(objet, attribut).model = role.model
        else:
            setattr(objet, attribut, create_llm_client(role, db))
    return bool(porteurs)


@admin_router.get("/cerveau/modeles")
async def lire_modeles(request: Request) -> dict:
    cfg = _wally(request).config
    cog = cfg.cognitive_loop or {}
    gate = cfg.response_gate or {}
    return {
        "fournisseurs": list(SUPPORTED_TEXT_PROVIDERS),
        # Défauts = ceux des lecteurs (`cognition_llm_config`, `setup_hook`).
        "cognition": {
            "enabled": bool(cog.get("enabled", False)),
            "provider": cog.get("provider", "deepseek"),
            "model_pro": cog.get("model_pro", "deepseek-v4-pro"),
        },
        "gate": {
            "enabled": bool(gate.get("enabled", False)),
            "provider": gate.get("provider", "deepseek"),
            "model": gate.get("model", "deepseek-v4-flash"),
        },
        "vision": {"model": cfg.openai.vision_model, "defaut": _VISION_DEFAUT},
        "temperatures": {
            role: {
                "provider": r.provider, "model": r.model,
                "temperature": r.temperature, "lue": _temperature_lue(r),
            }
            for role, r in (("primary", cfg.llm.primary), ("secondary", cfg.llm.secondary))
        },
        "tavily": asdict(cfg.tavily),
        "firecrawl": asdict(cfg.firecrawl),
    }


_TAVILY = {
    "monthly_limit": (_entier, "Recherches web par mois", 0, 100000),
    "cognitive_cooldown_minutes": (_entier, "Délai entre deux recherches de la cognition", 0, 1440),
}
_FIRECRAWL = {
    "enabled": (_booleen, "Lecture de pages web"),
    "daily_limit": (_entier, "Pages lues par jour", 0, 10000),
    "auto_scrape_links": (_booleen, "Lire les liens postés"),
    "auto_scrape_cooldown_s": (_entier, "Délai entre deux lectures de lien", 0, 3600),
    "inline_max_tokens": (_entier, "Taille d'une page lue", 100, 32000),
}


@admin_router.put("/cerveau/modeles")
async def ecrire_modeles(request: Request, body: dict) -> dict:
    state = _wally(request)
    cfg = state.config
    corps = _dict(body, "Modèles")
    inconnues = set(corps) - {"cognition", "gate", "vision", "temperatures", "tavily", "firecrawl"}
    if inconnues:
        raise _refus(f"Réglage inconnu : {', '.join(sorted(inconnues))}.")

    # ── Validation complète, AVANT toute mutation ──
    cognition = _lire(_dict(corps["cognition"], "Cognition"), {
        "provider": (_fournisseur, "Fournisseur de la cognition"),
        "model_pro": (_modele, "Modèle de la cognition"),
    }) if "cognition" in corps else {}
    gate = _lire(_dict(corps["gate"], "Filtre de réponse"), {
        "provider": (_fournisseur, "Fournisseur du filtre de réponse"),
        "model": (_modele, "Modèle du filtre de réponse"),
    }) if "gate" in corps else {}
    # Chaîne vide admise : elle rend la main au repli de `bootstrap.py`.
    vision = _lire(_dict(corps["vision"], "Vision"), {
        "model": (lambda v, lib: "" if v == "" else _modele(v, lib), "Modèle de vision"),
    }) if "vision" in corps else {}
    temperatures = _lire(_dict(corps["temperatures"], "Températures"), {
        "primary": (_nombre, "Température du modèle principal", 0, 2),
        "secondary": (_nombre, "Température du modèle secondaire", 0, 2),
    }) if "temperatures" in corps else {}
    tavily = _lire(_dict(corps["tavily"], "Recherche web"), _TAVILY) if "tavily" in corps else {}
    firecrawl = _lire(_dict(corps["firecrawl"], "Lecture de pages"), _FIRECRAWL) if "firecrawl" in corps else {}

    au_redemarrage: list[str] = []
    bot = state.discord_bot

    # ── Cognition : `cognition_llm_config` au boot → poussée dans les clients vivants ──
    if not isinstance(cfg.cognitive_loop, dict):
        cfg.cognitive_loop = {}
    if not isinstance(cfg.response_gate, dict):
        cfg.response_gate = {}
    # Seul ce qui CHANGE est poussé : réenregistrer la carte telle quelle ne
    # recrée aucun client et n'annonce aucun redémarrage.
    cognition = {k: v for k, v in cognition.items() if cfg.cognitive_loop.get(k) != v}
    gate = {k: v for k, v in gate.items() if cfg.response_gate.get(k) != v}
    if vision and vision["model"] == cfg.openai.vision_model:
        vision = {}

    if cognition:
        from bot.discord.bot import cognition_llm_config
        avant = cfg.cognitive_loop.get("provider", "deepseek")
        cfg.cognitive_loop.update(cognition)
        role = cognition_llm_config(cfg.cognitive_loop, cfg.llm)
        if not _pousser_client(_clients_cognition(state), avant, role, state.db):
            au_redemarrage.append("modèle de la cognition")

    # ── Filtre de réponse : `ResponseGate._llm`, construit au boot ──
    if gate:
        from bot.config import LLMRoleConfig
        avant = cfg.response_gate.get("provider", "deepseek")
        cfg.response_gate.update(gate)
        role = LLMRoleConfig(provider=cfg.response_gate.get("provider", "deepseek"),
                             model=cfg.response_gate.get("model", "deepseek-v4-flash"))
        filtre = getattr(bot, "response_gate", None)
        porteurs = [(filtre, "_llm")] if getattr(filtre, "_llm", None) is not None else []
        if not _pousser_client(porteurs, avant, role, state.db):
            au_redemarrage.append("modèle du filtre de réponse")

    # ── Vision : `VisionService._client`, un OpenAILLMClient construit au boot ──
    if vision:
        cfg.openai.vision_model = vision["model"]
        client = getattr(getattr(bot, "vision", None), "_client", None)
        if client is not None:
            client.model = vision["model"] or _VISION_DEFAUT
        else:
            au_redemarrage.append("modèle de vision")

    # ── Températures : lues à chaque appel par les clients principal/secondaire ──
    if "primary" in temperatures:
        cfg.llm.primary.temperature = temperatures["primary"]
        # `openai:` est le miroir de `llm.primary` (cf. `Config.load`).
        cfg.openai.temperature = temperatures["primary"]
        state.primary_llm.temperature = temperatures["primary"]
    if "secondary" in temperatures:
        cfg.llm.secondary.temperature = temperatures["secondary"]
        state.secondary_llm.temperature = temperatures["secondary"]

    # ── Recherche web : quota relu par `WebSearchService` ; le délai de la
    # cognition est capturé par `CognitiveLoop.__init__` → poussé en place ──
    for cle, valeur in tavily.items():
        setattr(cfg.tavily, cle, valeur)
    if "cognitive_cooldown_minutes" in tavily:
        boucle = getattr(bot, "cognitive_loop", None)
        if boucle is not None and hasattr(boucle, "_web_search_cooldown_s"):
            boucle._web_search_cooldown_s = tavily["cognitive_cooldown_minutes"] * 60
        else:
            au_redemarrage.append("délai de recherche de la cognition")

    # ── Lecture de pages : tout relu à chaque usage (`ScrapeService`, handlers) ──
    for cle, valeur in firecrawl.items():
        setattr(cfg.firecrawl, cle, valeur)

    cfg.save()
    if au_redemarrage:
        logger.info("Réglages cerveau rangés, au prochain redémarrage : {r}", r=au_redemarrage)
    return {"status": "saved", "au_redemarrage": au_redemarrage}


# ── 4. Images spontanées ────────────────────────────────────────────────────

# Lecteur : `core/image_initiative.py`, relu à chaque décision (et par
# `ReasoningAgent` à chaque tick pour annoncer les salons) → à chaud. Seule la
# phrase du self-model des CONVERSATIONS (`persona.image_channels`) est calculée
# au boot : le panel le dit.
_IMAGES = {
    "autonomous_enabled": (_booleen, "Images de sa propre initiative"),
    "autonomous_daily_limit": (_entier, "Images par jour", -1, 50),
    "autonomous_cooldown_minutes": (_entier, "Délai entre deux images", 0, 10080),
}


@admin_router.get("/cerveau/images-autonomes")
async def lire_images(request: Request) -> dict:
    cfg = _wally(request).config
    ig = cfg.image_generation
    cog = cfg.cognitive_loop or {}
    return {
        **{cle: getattr(ig, cle) for cle in _IMAGES},
        "autonomous_channel_ids": [str(c) for c in ig.autonomous_channel_ids],
        "cognition_active": bool(cog.get("enabled", False)) if isinstance(cog, dict) else False,
    }


@admin_router.put("/cerveau/images-autonomes")
async def ecrire_images(request: Request, body: dict) -> dict:
    state = _wally(request)
    corps = dict(_dict(body, "Images spontanées"))
    salons = None
    if "autonomous_channel_ids" in corps:
        brut = corps.pop("autonomous_channel_ids")
        if not isinstance(brut, list):
            raise _refus("Salons : une liste est attendue.")
        salons = []
        for s in brut:
            texte = str(s).strip()
            # Chaînes de chiffres : un snowflake ne survit pas à un `Number` JS.
            if isinstance(s, bool) or not texte.isdigit():
                raise _refus(f"Salons : « {texte[:30]} » n'est pas un identifiant de salon.")
            if texte not in salons:
                salons.append(texte)
    valeurs = _lire(corps, _IMAGES)
    ig = state.config.image_generation
    ouvert_avant = (ig.autonomous_enabled, list(ig.autonomous_channel_ids))
    for cle, valeur in valeurs.items():
        setattr(ig, cle, valeur)
    if salons is not None:
        ig.autonomous_channel_ids = salons
    state.config.save()
    ouverture = ouvert_avant != (ig.autonomous_enabled, list(ig.autonomous_channel_ids))
    return {"status": "saved",
            "au_redemarrage": ["la phrase qui l'annonce dans les conversations"] if ouverture else []}
