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
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from loguru import logger

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
from bot.core.overlay_elements import LIBELLES              # noqa: E402
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
    """Tout le modèle, plus les libellés lisibles des éléments.

    Les libellés voyagent AVEC le layout au lieu d'avoir leur route : le panneau
    fait déjà cet appel au chargement, et un second aller-retour pour trente-
    quatre chaînes constantes ne se justifie pas. Le PUT, lui, ne les renvoie
    pas — le panneau garde ceux du chargement plutôt que de les réclamer.
    """
    layout = await charger_layout(_db(request))
    return {**layout, "libelles": LIBELLES}


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


# ── Le bouton « Tester » ─────────────────────────────────────────────────────
#
# Un jeu de paramètres par widget, calé sur le SCHÉMA de chaque builder
# (`overlay.js`, `overlay_apex.js`). Un widget testé sans paramètre se
# construirait vide et ne dirait rien de son encombrement réel — or c'est
# exactement ce qu'on cherche à voir en le plaçant.
#
# Les valeurs sont volontairement LONGUES là où la largeur varie (le sondage à
# quatre options, le versus, le message épinglé) : on règle sur le pire cas,
# pas sur le cas commode.
_ECHANTILLONS: dict[str, dict] = {
    "coinflip":  {"result": "heads"},
    # `results` et pas `count` : c'est la liste que lit le builder, et un seul
    # dé occupe 78 px là où deux en prennent le double — l'encombrement montré
    # doit être celui qu'on aura vraiment.
    "dice":      {"result": "4", "results": ["4", "2"]},
    "wheel":     {"options": ["Fuse", "Bloodhound", "Rampart", "Mirage"],
                  "result": 0},
    "countdown": {"seconds": 60, "done": "C'est l'heure"},
    # `gauge` porte AUSSI l'objectif de follows/subs : `_publish_goal` publie
    # une jauge, pas un widget « goal ».
    "gauge":     {"percent": 62, "label": "Objectif follows · 31/50"},
    "pinned":    {"text": "Un message du chat, assez long pour occuper "
                          "toute la largeur prévue", "author": "kassandreyunikon"},
    # `counter` porte AUSSI l'uptime, aliasé à la publication.
    "counter":   {"text": "12 morts en tombant"},
    "clip":      {"title": "Le rageur Taki", "creator": "kassandreyunikon"},
    "clip_top":  {"rows": [{"title": "Le rageur Taki", "views": 412},
                           {"title": "Le cerveau de Rina a bug", "views": 208}]},
    "prediction": {"bet": "Azraël finit top 5", "outcome": "wrong"},
    "quote":     {"text": "Dans le doute, je fais exploser la maison",
                  "author": "Azraël"},
    "raid":      {"from": "kingsrequin", "viewers": 42},
    "wave":      {"viewers": 120},
    "poll":      {"question": "On enchaîne sur du classé ?",
                  "options": ["Oui", "Non", "Une pause d'abord", "Peu importe"],
                  "seconds": 20},
    "stats":     {"player": "Azraël",
                  "lines": ["Rang : Platine 4", "RP : 8 756",
                            "Kills : 102 324", "3ᵉ mondial avec Fuse"]},
    "versus":    {"label": "Kills", "left_name": "Azraël", "left_value": 18,
                  "right_name": "KingsRequin", "right_value": 7},
    "bingo":     {"cells": ["Azra tombe de la map", "Kassandre parle en fight",
                            "Un random qui ping tout", "Zéro dégât sur un fight",
                            "Requin explique Mirage", "Fuse ulti dans le vide"],
                  "check": 0},
    "rps":       {"move": "pierre"},
    "hangman":   {"word": "octane", "hint": "il court vite"},
    # `talkers` lit `rows`, pas une liste nue : sans elles, la carte se réduit
    # à son titre et ne dit rien de la place qu'elle prendra en direct.
    "talkers":   {"rows": [{"name": "kassandreyunikon", "count": 128},
                           {"name": "KingsRequin", "count": 96},
                           {"name": "Azraël", "count": 41}]},
    # Les huit panneaux Apex passent par `APEX_BUILDERS` et se placent comme
    # les autres : sans échantillon, leur ▶ n'aurait affiché qu'un cadre vide.
    "apex_rank":     {"player": "Azraël", "rank_name": "Platine", "div": "IV",
                      "score": 8756, "top_percent": 12, "ladder_pos": 41230},
    "apex_status":   {"player": "Azraël", "in_game": True, "state": "En partie",
                      "legend": "Fuse", "skin": "Le Roi des Explosifs",
                      "level": 412},
    "apex_stats":    {"player": "Azraël",
                      "rows": [{"label": "Kills", "value": 102324, "top_percent": 3},
                               {"label": "Dégâts", "value": 18402993},
                               {"label": "Parties jouées", "value": 24118}]},
    "apex_map":      {"modes": [{"name": "Battle Royale", "map": "Storm Point",
                                 "remaining_s": 1240},
                                {"name": "Classé", "map": "World's Edge",
                                 "remaining_s": 3600}]},
    "apex_craft":    {"bundles": [{"type": "Quotidien",
                                   "items": ["Chargeur lourd", "Crosse de fusil"]},
                                  {"type": "Hebdomadaire",
                                   "items": ["Viseur 2x-4x", "Bouclier de bras"]}]},
    "apex_predator": {"rows": [{"platform": "PC", "rp": 173420},
                               {"platform": "PS4", "rp": 141288},
                               {"platform": "Xbox", "rp": 138904}]},
    "apex_servers":  {"rows": [{"name": "Europe (Francfort)", "status": "en ligne",
                                "up": True},
                               {"name": "Tokyo", "status": "hors ligne",
                                "up": False}]},
    # `meme` et `planning` n'ont pas d'échantillon écrit : leur seul paramètre
    # est une URL d'image, et une URL inventée afficherait une image cassée.
    # `_source_image()` va chercher un vrai fichier au moment de l'appel.
    "meme":      {},
    "planning":  {},
}

# Ce qui ne passe pas par un builder de widget. Publier un `widget` de ces
# noms-là ne ferait rien du tout côté page (`BUILDERS[kind]` est indéfini,
# `showWidget` sort) : le ▶ resterait muet et passerait pour une panne. On dit
# donc POURQUOI, ce qui est la seule chose utile à savoir ici.
_HORS_WIDGET: dict[str, str] = {
    "rotator": "Le rotateur de memes est une source OBS à part "
               "(/overlay-rotation) : il tourne tout seul, hors de cette page.",
    "image": "L'image de la galerie a sa propre source OBS (/overlay-image) : "
             "elle ne s'affiche pas sur cette page.",
    "apex_progress": "La courbe se trace sur de vrais relevés : sans "
                     "historique, le panneau se retire de lui-même.",
}

# Ce que dure un élément d'essai à l'écran. Plus long qu'un widget de live
# (10 s) : on le règle en le regardant, et republier à chaque coup d'œil
# rallongerait le geste pour rien.
_DUREE_ESSAI_S = 20.0


def _source_image(cle: str, request: Request) -> str | None:
    """L'URL d'image des deux widgets qui n'en portent qu'une, ou `None`.

    Un `src` vide donne un `<img>` cassé, de 13 px de côté : le widget serait
    annoncé « affiché » sans rien montrer, et le placement se ferait toujours à
    l'aveugle — exactement le bouton muet qu'on cherche à éviter. On prend donc
    un vrai fichier, ou on ne publie rien et on dit pourquoi.
    """
    if cle == "planning":
        from bot.intelligence.overlay_narrator import PLANNING_PATH
        # Le fichier est servi par `/static` : son chemin sur le disque s'en
        # déduit. Absent, l'image serait cassée dans l'aperçu sans un mot.
        nom = PLANNING_PATH.split("/static/", 1)[-1]
        return PLANNING_PATH if (_STATIC_DIR / nom).exists() else None
    library = getattr(request.app.state.wally, "memes", None)
    medias = library.list() if library is not None else []
    if not medias:
        return None
    return f"/api/public/meme/{quote(medias[0]['name'])}"


# Ce qu'on répond quand l'image d'exemple manque. Nommé ici : les deux cas
# n'ont pas la même cause, et « ça ne marche pas » n'aide personne.
_SANS_IMAGE = {
    "meme": "Aucun meme dans la bibliothèque de la chaîne : il n'y a rien à "
            "afficher. Déposez-en un, puis réessayez.",
    "planning": "L'image du planning est absente de `static/fichiers/` : "
                "l'élément s'affichera vide tant qu'elle manque.",
}


@admin_router.post("/overlay/preview")
async def post_overlay_preview(request: Request) -> dict:
    """Affiche un élément — ou tous — sur UNE scène, pour la régler.

    Le champ `scene` est le cœur de la fonction : sans lui, tester un dé
    pendant qu'on prépare la scène de fin le ferait surgir en plein live.
    `overlay.js` écarte tout événement qui porte un slug autre que le sien.
    """
    from bot.core.overlay_layout import ELEMENTS
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")
    if not isinstance(data, dict):
        raise HTTPException(400, "JSON invalide")
    slug = str(data.get("scene") or "")
    if not slug:
        raise HTTPException(400, "scene requise")
    feed = getattr(request.app.state.wally, "overlay_feed", None)
    if feed is None:
        raise HTTPException(503, "Bus overlay indisponible")

    if data.get("tous"):
        layout = await charger_layout(_db(request))
        scene = scene_par_slug(layout, slug)
        if scene is None:
            # Contrairement à la page publique, qui sert le défaut plutôt qu'un
            # écran noir en plein live : ici c'est un appel d'administration, et
            # une scène absente est une erreur de l'appelant.
            raise HTTPException(404, "Scène inconnue")
        feed.publish({"type": "ghosts", "scene": slug,
                      "elements": scene["elements"]})
        logger.info("Overlay : repères de tous les éléments sur « {s} »", s=slug)
        return {"ok": True, "affiche": True}

    cle = str(data.get("element") or "")
    if cle not in ELEMENTS:
        raise HTTPException(400, f"Élément inconnu : {cle}")

    if cle == "avatar":
        # L'avatar n'est pas un widget : il est à l'écran en permanence — SAUF
        # quand une carte `solo` prend la scène, qui l'efface le temps de son
        # passage. Répondre « il est déjà là » à quelqu'un qui le voit effacé
        # est pire que ne rien répondre : le message contredit l'écran, et on
        # cherche la panne ailleurs. Le ▶ fait donc la seule chose utile pour
        # lui — il dégage la scène, et l'avatar revient.
        feed.publish({"type": "clear", "scene": slug})
        logger.info("Overlay : scène « {s} » dégagée, l'avatar revient", s=slug)
        return {"ok": True, "affiche": True,
                "message": "Scène dégagée : l'avatar est de nouveau à l'écran. "
                           "Les cartes et repères d'essai en cours sont retirés."}

    if cle in _HORS_WIDGET:
        return {"ok": True, "affiche": False, "raison": _HORS_WIDGET[cle]}

    if cle == "bubble":
        # La bulle a son propre événement — elle n'est pas un widget. Publiée
        # ici sans passer par `feed.say()` : celui-ci trace « tu as sorti une
        # bulle sur ton overlay » dans la mémoire de soi, ce qui ferait
        # commenter à Wally une réplique qu'il n'a jamais eue.
        feed.publish({
            "type": "bubble", "scene": slug, "mode": "speech",
            "text": "Voilà à quoi ressemble une bulle un peu bavarde, "
                    "posée là pour régler sa place.",
            "duration": _DUREE_ESSAI_S,
        })
        logger.info("Overlay : bulle d'essai sur « {s} »", s=slug)
        return {"ok": True, "affiche": True}

    params = {**_ECHANTILLONS.get(cle, {}), "duration": _DUREE_ESSAI_S}
    if cle in _SANS_IMAGE:
        src = _source_image(cle, request)
        if src is None:
            return {"ok": True, "affiche": False, "raison": _SANS_IMAGE[cle]}
        params["src"] = src
    # `sticky` est retiré de force : un widget collant est REJOUÉ sans jamais
    # périmer à chaque reconnexion (`OverlayFeed.recent`). Un pendu d'essai
    # hanterait la scène qu'on vient de régler jusqu'au prochain vrai pendu.
    params.pop("sticky", None)
    feed.publish({"type": "widget", "scene": slug, "kind": cle, "params": params})
    logger.info("Overlay : essai du widget « {k} » sur « {s} »", k=cle, s=slug)
    return {"ok": True, "affiche": True}
