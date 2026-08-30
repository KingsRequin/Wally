"""« Remontre l'image que t'avais faite de moi en pirate » — ses propres images.

Wally génère des images, par `/imagine` et de sa propre initiative via l'ACTE
cognitif `generate_image`. Chacune est rangée dans `gallery_images` avec son
prompt, son demandeur et sa date — et il n'avait **aucun moyen de les relire**.
La table n'était lue que par le journal, l'initiative, le dashboard et la route
galerie ; jamais par un outil.

L'outil qui RESSEMBLAIT à ce qu'il fallait n'en est pas un : `image_search`
cherche sur le web, sa description dit « Find an image on the web ».

Une image générée est un ACTE de Wally, au même titre qu'une phrase — et c'était
le seul de ses actes dont il ne gardait aucun accès. Il se souvenait de ce qu'on
lui avait dit, pas de ce qu'il avait fabriqué.

## Ce qui n'est PAS offert, et pourquoi

Pas de filtre « par demandeur » : « l'image de MOI en pirate » désigne le sujet,
qui est dans le PROMPT, pas la personne qui l'a commandée. Une recherche libre
répond aux deux formulations, et 7 images en base (relevé du 2026-08-30) ne
justifient pas un second axe que personne ne réclame.

Pas de tri par votes non plus : ils sont rendus dans chaque résultat, le modèle
lit « 3 personnes ont voté pour » sans avoir à choisir un ordre.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# Assez pour retrouver la bonne parmi des variantes, pas assez pour réciter la
# galerie. Le modèle en cite une ou deux, jamais cinq.
_MAX = 5

# Le prompt d'origine peut faire un paragraphe : borné, il sert à RECONNAÎTRE
# l'image, pas à la reconstituer.
_PROMPT_MAX = 140

GALLERY_TOOL = {
    "type": "function",
    "function": {
        "name": "my_images",
        "description": (
            "Les images que TU as fabriquées, avec leur sujet, leur date et leur "
            "lien. Sers-t'en quand on te parle d'une image que tu as faite "
            "(« remontre celle de moi en pirate », « c'était quoi ton dernier "
            "dessin ? », « t'avais fait un truc avec un requin non ? »). "
            "N'invente JAMAIS une image que tu aurais faite : si cette liste est "
            "vide, c'est que tu ne l'as pas faite. Rien à voir avec une "
            "recherche d'image sur le web."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sujet": {
                    "type": "string",
                    "description": (
                        "Un ou deux mots du sujet de l'image (« pirate », "
                        "« requin gâteau »). Laisse VIDE pour tes dernières."
                    ),
                },
            },
        },
    },
}


def _il_y_a(created_at: str) -> str:
    """« il y a 3 jours », depuis un `created_at` SQL.

    ⚠️ `gallery_images.created_at` est un **datetime SQL en UTC**
    (« 2026-08-27 22:38:20 »), pas un timestamp Unix : le lire comme un nombre
    daterait toutes les images de 1970. Le modèle calcule mal les écarts de
    dates — on lui rend la durée déjà faite, comme `follow_date`.
    """
    try:
        quand = datetime.fromisoformat(str(created_at)).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return "à une date inconnue"
    jours = max((datetime.now(timezone.utc) - quand).days, 0)
    if jours == 0:
        return "aujourd'hui"
    if jours == 1:
        return "hier"
    if jours < 31:
        return f"il y a {jours} jours"
    mois = jours // 30
    return f"il y a {mois} mois" if mois < 12 else f"il y a {mois // 12} an(s)"


def _lien(image_id: str) -> str:
    """L'URL publique de l'image. `WEB_BASE_URL` est déjà la base du projet."""
    base = os.getenv("WEB_BASE_URL", "").rstrip("/")
    return f"{base}/api/public/gallery/{image_id}/image" if base else ""


async def run_gallery_tool(bot: Any, args: dict) -> str:
    """Ses propres images, les plus récentes d'abord."""
    db = getattr(bot, "db", None)
    if db is None:
        return json.dumps({"status": "unavailable",
                           "message": "Je n'ai pas accès à ma galerie."})

    sujet = str(args.get("sujet") or "").strip()
    try:
        # `sujet_seulement` : sans lui, le LIKE porte aussi sur le pseudo du
        # demandeur — « remontre l'image du requin » ramenait tout ce que
        # KingsRequin avait commandé. Le dashboard, lui, garde le pseudo dans
        # sa recherche, c'est ce qu'on y cherche.
        images = await db.get_gallery_images(
            search=sujet or None, limit=_MAX, sujet_seulement=True
        )
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.warning("Galerie illisible : {e!r}", e=exc)
        return json.dumps({"status": "error", "message": (
            "Je n'arrive pas à relire ma galerie, dis-le plutôt que d'inventer "
            "une image.")}, ensure_ascii=False)

    if not images:
        return json.dumps({"status": "vide", "message": (
            f"Je n'ai fait aucune image de « {sujet} »." if sujet
            else "Je n'ai encore fabriqué aucune image."
        )}, ensure_ascii=False)

    rendu = []
    for img in images:
        # `username` vaut « Wally » quand l'image vient de sa propre initiative
        # plutôt que d'une demande : le dire évite qu'il l'attribue à quelqu'un.
        demandeur = str(img.get("username") or "").strip()
        fiche = {
            "sujet": str(img.get("title") or img.get("prompt") or "")[:_PROMPT_MAX],
            "quand": _il_y_a(str(img.get("created_at") or "")),
            "a_ta_propre_initiative": demandeur.lower() == "wally",
        }
        if not fiche["a_ta_propre_initiative"] and demandeur:
            fiche["demandee_par"] = demandeur
        votes = int(img.get("votes") or 0)
        if votes:
            fiche["votes"] = votes
        lien = _lien(str(img.get("id") or ""))
        if lien:
            fiche["lien"] = lien
        rendu.append(fiche)

    return json.dumps({
        "status": "ok",
        "images": rendu,
        "note": (
            "Ce sont TES images. Pour en remontrer une, écris son lien tel quel "
            "— il s'affiche tout seul. N'en cite qu'une ou deux, à ta façon."
        ),
    }, ensure_ascii=False)
