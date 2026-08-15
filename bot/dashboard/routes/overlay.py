# bot/dashboard/routes/overlay.py
"""Routes de l'overlay de stream : télémétrie de rendu + déclencheur de test.

La télémétrie vient de l'overlay lui-même (fps, pire frame, GPU) : c'est la
seule mesure possible côté page — l'usage GPU système est illisible depuis un
navigateur, et la vraie validation reste les stats OBS chez le streamer.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from bot.core.memes import media_type

public_router = APIRouter()
admin_router = APIRouter()

# Bornes défensives : la télémétrie vient d'une page publique non authentifiée,
# on ne stocke que des valeurs plausibles et une seule entrée (pas de liste qui
# grossit sous des POST hostiles).
_MAX_GPU_LEN = 120


# Empreinte des fichiers réellement servis. `static/` est bind-monté : une
# modification est visible sans rebuild, mais OBS garde sa page en mémoire des
# heures. L'overlay interroge donc cette version et se recharge tout seul.
_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
# TOUS les fichiers que la page charge, pas seulement les deux principaux.
# `overlay_apex.js` et les bibliothèques de `vendor/` en étaient absents : ils
# n'avaient pas d'empreinte dans leur URL et ne comptaient pas dans la version,
# donc OBS gardait indéfiniment la copie du premier chargement. Un panneau Apex
# corrigé ne serait jamais arrivé à l'écran.
_OVERLAY_FILES = (
    "overlay.html",
    "overlay.js",
    "overlay_layout.js",
    "overlay_apex.js",
    "glitch.js",
    "vendor/canvas-confetti.js",
    "vendor/spin-wheel.js",
)
_version_cache: dict = {"stamp": None, "value": "0"}

# Les `<script src="/static/….js">` de la page. Volontairement limité au JS :
# la vidéo de l'avatar pèse lourd et n'a aucune raison d'être retéléchargée
# parce qu'un script a bougé.
_STATIC_SCRIPT_RE = re.compile(r'src="(/static/[^"?]+\.js)"')


def version_static_scripts(html: str, version: str) -> str:
    """Ajoute l'empreinte à chaque script statique de la page.

    Le HTML n'est jamais mis en cache, les scripts si : sans cette empreinte
    dans l'URL, un rechargement resservirait les anciens fichiers.
    """
    return _STATIC_SCRIPT_RE.sub(rf'src="\1?v={version}"', html)


def overlay_version() -> str:
    """Empreinte courte du contenu de l'overlay.

    Basée sur le CONTENU et non sur la date : un `touch`, un redéploiement à
    l'identique ou un simple redémarrage ne doivent pas provoquer de
    rechargement en plein live.
    """
    # Un fichier manquant compte comme absent, il n'interrompt PAS le calcul.
    # Avec un seul `try` autour de la liste entière, il suffisait qu'une des
    # bibliothèques de `vendor/` n'ait pas été déployée pour que la version
    # reste figée sur sa valeur en cache — donc plus aucune détection de mise à
    # jour, silencieusement, pour tous les autres fichiers.
    def _stamp(name: str):
        try:
            return (_STATIC_DIR / name).stat().st_mtime_ns
        except OSError:
            return None

    stamp = tuple(_stamp(name) for name in _OVERLAY_FILES)
    if stamp == _version_cache["stamp"]:
        return _version_cache["value"]
    digest = hashlib.sha1()
    for name in _OVERLAY_FILES:
        try:
            digest.update((_STATIC_DIR / name).read_bytes())
        except OSError:
            pass
    _version_cache.update(stamp=stamp, value=digest.hexdigest()[:10])
    return _version_cache["value"]


@public_router.get("/meme/{name}")
async def get_meme(name: str, request: Request):
    """Sert une image du dossier des memes.

    Publique parce que l'overlay tourne dans OBS sans session. `resolve` refuse
    tout nom qui sortirait du dossier — c'est la seule barrière, elle est donc
    stricte.
    """
    library = getattr(request.app.state.wally, "memes", None)
    if library is None:
        raise HTTPException(404, "Aucune bibliothèque de memes")
    path = library.resolve(name)
    if path is None:
        raise HTTPException(404, "Meme introuvable")
    return FileResponse(
        path,
        media_type=media_type(path),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@public_router.get("/rotation")
async def get_rotation(request: Request) -> dict:
    """Liste des médias du rotateur : nom et genre, rien d'autre.

    Publique parce que la page tourne dans OBS sans session. Ne lève jamais :
    une source de live préfère une liste vide à une erreur, qu'elle ne saurait
    pas distinguer d'une panne du bot — et sur laquelle elle s'acharnerait.

    La clé s'appelle `name` côté bibliothèque (`list_medias` suit `list`, qui
    existait avant) et `nom` côté JSON. La conversion se fait ici, une seule fois.
    """
    library = getattr(request.app.state.wally, "memes", None)
    if library is None:
        return {"medias": []}
    return {"medias": [
        {"nom": m["name"], "genre": m["genre"]} for m in library.list_medias()
    ]}


@public_router.get("/overlay-version")
async def get_overlay_version() -> dict:
    """Version courante — l'overlay la compare à la sienne toutes les 30 s."""
    return {"version": overlay_version()}


@public_router.post("/overlay-health")
async def overlay_health(request: Request) -> dict:
    """Reçoit la télémétrie de rendu envoyée toutes les 10 s par l'overlay."""
    state = request.app.state.wally
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    fps = data.get("fps")
    worst = data.get("worst_frame_ms")
    # `json.loads` accepte `NaN` et `Infinity` : ce sont des `float`, ils
    # passaient le test de type, puis `int(nan)` levait ValueError et
    # `int(inf)` OverflowError — un 500 répétable, sans authentification.
    if (not isinstance(fps, (int, float)) or isinstance(fps, bool)
            or not isinstance(worst, (int, float)) or isinstance(worst, bool)
            or not math.isfinite(fps) or not math.isfinite(worst)):
        raise HTTPException(400, "fps et worst_frame_ms requis (nombres finis)")
    state.overlay_health = {
        "fps": max(0, min(240, int(fps))),
        "worst_frame_ms": max(0, min(10_000, int(worst))),
        "gpu": str(data.get("gpu", ""))[:_MAX_GPU_LEN],
        "at": time.time(),
    }
    return {"ok": True}


@admin_router.get("/overlay/health")
async def get_overlay_health(request: Request) -> dict:
    """Dernière télémétrie reçue — visible depuis le dashboard, sans rien
    demander au streamer pendant qu'il joue."""
    health = getattr(request.app.state.wally, "overlay_health", None)
    if not health:
        return {"connected": False}
    # Au-delà de 30 s sans nouvelle (émission toutes les 10 s), l'overlay est
    # considéré déconnecté.
    return {"connected": time.time() - health["at"] < 30, **health}


def _narrator(request: Request):
    """Le narrateur est construit avec le bot Discord : absent avant sa connexion."""
    narrator = getattr(
        getattr(request.app.state.wally, "discord_bot", None), "overlay_narrator", None
    )
    if narrator is None:
        raise HTTPException(503, "Narrateur d'overlay indisponible")
    return narrator


@admin_router.get("/overlay/force-live")
async def get_force_live(request: Request) -> dict:
    """Minutes restantes de mode test — le bouton du panneau reflète l'état réel,
    y compris quand l'échéance est tombée toute seule."""
    narrator = _narrator(request)
    remaining = narrator.force_live_remaining()
    return {"active": remaining > 0, "remaining_minutes": round(remaining, 1)}


@admin_router.post("/overlay/force-live")
async def set_force_live(request: Request) -> dict:
    """Active (ou coupe) le mode test hors live.

    Toujours borné dans le temps : oublié actif, il ferait parler Wally dans le
    vide à un appel LLM la bulle.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data.get("active") is False:
        minutes = 0.0
    else:
        try:
            minutes = float(data.get("minutes", 30))
        except (TypeError, ValueError):
            raise HTTPException(400, "minutes invalide")
        # `math.isfinite` comme sur `overlay_health` 60 lignes plus haut :
        # `NaN` passe `float()` sans lever, puis `nan <= 0` est faux,
        # `min(nan, 120)` rend `nan`, et `round(nan, 1)` fait échouer la
        # sérialisation → 500 sur un POST admin. Pire, `flush_force_live` a déjà
        # persisté « nan » : au redémarrage l'échéance restait `nan` et le mode
        # test était mort en silence (toute comparaison contre `nan` est fausse).
        if not math.isfinite(minutes):
            raise HTTPException(400, "minutes invalide")
    narrator = _narrator(request)
    granted = narrator.force_live(minutes)
    # Rangé tout de suite : un rebuild peut arriver dans la minute, et c'est
    # précisément entre deux déploiements qu'on se sert du mode test.
    await narrator.flush_force_live()
    return {"active": granted > 0, "remaining_minutes": round(granted, 1)}


@admin_router.post("/overlay/test")
async def overlay_test(request: Request) -> dict:
    """Publie un événement de test sur l'overlay (réglage visuel sans attendre
    un vrai événement de stream)."""
    state = request.app.state.wally
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    kind = data.get("type", "bubble")
    if kind == "bubble":
        text = (data.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text requis")
        state.overlay_feed.say(text, mode=data.get("mode", "speech"))
    elif kind == "thinking":
        state.overlay_feed.thinking(bool(data.get("active", True)))
    elif kind == "react":
        state.overlay_feed.react(str(data.get("kind", "test")))
    elif kind == "widget":
        widget = str(data.get("widget") or "").strip()
        if not widget:
            raise HTTPException(400, "widget requis")
        params = data.get("params")
        state.overlay_feed.widget(widget, **(params if isinstance(params, dict) else {}))
    else:
        raise HTTPException(400, f"type inconnu: {kind}")
    return {"ok": True, "subscribers": state.overlay_feed.subscriber_count}


# ── Mise en scène ────────────────────────────────────────────────────────────
from bot.core.overlay_layout import scene_par_slug          # noqa: E402
from bot.core.overlay_layout_store import (                 # noqa: E402
    charger_layout, enregistrer_layout,
)


def _db(request: Request):
    """La base, ou None avant la connexion du bot. `charger_layout` l'accepte."""
    return getattr(request.app.state.wally, "db", None)


@public_router.get("/overlay-layout")
async def get_overlay_layout(request: Request, scene: str = "") -> dict:
    """Le layout d'une scène — ce que la page lit au démarrage.

    Source de vérité, plutôt qu'un événement SSE qui pourrait ne jamais venir :
    une page ouverte alors que le bus est muet doit quand même se placer.
    """
    layout = await charger_layout(_db(request))
    slug = scene or layout["defaut"]
    trouvee = scene_par_slug(layout, slug)
    if trouvee is None:
        # Scène supprimée alors qu'OBS pointe encore dessus : on sert le défaut
        # plutôt qu'un 404 qui laisserait l'écran vide en plein live.
        trouvee = scene_par_slug(layout, layout["defaut"]) or layout["scenes"][0]
    return {"scene": trouvee, "defaut": layout["defaut"]}


@admin_router.get("/overlay/layout")
async def get_overlay_layout_admin(request: Request) -> dict:
    """Tout le modèle — le panneau a besoin de toutes les scènes."""
    return await charger_layout(_db(request))


@admin_router.put("/overlay/layout")
async def put_overlay_layout(request: Request) -> dict:
    """Enregistre et publie. Le retour est ce qui a été RANGÉ, pas ce qui a été
    envoyé : le panneau voit donc immédiatement les valeurs bornées."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    layout = await enregistrer_layout(_db(request), data)
    feed = getattr(request.app.state.wally, "overlay_feed", None)
    if feed is not None:
        # Un SIGNAL, pas le layout. `OverlayFeed.recent()` rejoue les dix
        # derniers événements à chaque connexion (overlay_feed.py:105) : y
        # pousser le modèle entier chasserait des bulles utiles du tampon, et
        # une page qui se connecte démarrerait sur un écran vide. La page refait
        # son GET, qui reste la seule source de vérité.
        #
        # `scene: None` — toutes les pages ouvertes se replacent. Chacune ne
        # retient que la scène qui la concerne.
        feed.publish({"type": "layout", "scene": None})
    return layout
