# bot/dashboard/routes/music.py
"""La porte de l'extension qui suit la musique d'Azraël.

Une seule route, appelée depuis le NAVIGATEUR D'UN TIERS à travers internet :
l'extension bat toutes les deux secondes, dit ce qui passe, et repart avec les
ordres en attente.

Elle porte son propre jeton plutôt que celui du dashboard : confier le Bearer
admin à une extension installée sur une autre machine reviendrait à lui donner
la mémoire, les logs et les DM. Même parti pris que `/api/chat/`, qui valide son
JWT dans chaque route.
"""
from __future__ import annotations

import io
import secrets
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from loguru import logger

router = APIRouter()
public_router = APIRouter()

# Le dossier de l'extension, tel qu'il est copié dans l'image (cf. Dockerfile).
_EXTENSION_DIR = Path(__file__).resolve().parents[3] / "extension-musique"

# L'extension s'exécute dans l'onglet YouTube : c'est de cette origine que la
# requête part. Fermée à tout le reste — un CORS ouvert laisserait n'importe
# quel site visité par n'importe qui tenter sa chance sur cette route.
ORIGINES = ("https://www.youtube.com", "https://music.youtube.com")

_MAX_ACCUSES = 10


def _service(request: Request):
    service = getattr(request.app.state.wally, "music", None)
    if service is None:
        raise HTTPException(503, "Service musique indisponible")
    return service


def _verifier_jeton(request: Request) -> None:
    """Le jeton attendu, comparé en temps constant.

    Un jeton NON CONFIGURÉ ferme la porte au lieu de l'ouvrir : le champ est
    vide tant que personne ne l'a rempli, et cette route est publiée sur
    internet.
    """
    attendu = str(getattr(getattr(request.app.state.wally.config, "music", None),
                          "extension_token", "") or "")
    if not attendu:
        raise HTTPException(503, "Jeton de l'extension musique non configuré")
    entete = request.headers.get("Authorization", "")
    presente = entete[7:] if entete.startswith("Bearer ") else ""
    if not presente or not secrets.compare_digest(presente, attendu):
        raise HTTPException(401, "Jeton invalide")


@router.post("/beat")
async def beat(request: Request) -> dict:
    """Le battement de l'extension. Rend les ordres en attente.

    Tolérante sur la FORME du corps, stricte sur le jeton : elle est appelée par
    un navigateur qu'on ne contrôle pas, et un 500 répétable y serait une panne
    visible en plein live. Les champs absents ou tordus retombent sur des
    valeurs neutres — c'est le service qui borne et range.
    """
    _verifier_jeton(request)
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 — corps illisible = 400, jamais 500
        raise HTTPException(400, "JSON invalide")
    if not isinstance(data, dict):
        raise HTTPException(400, "JSON invalide")

    accuses = data.get("accuses")
    if not isinstance(accuses, list):
        accuses = []

    try:
        ordres = _service(request).battement(
            actif=bool(data.get("actif")),
            joue=bool(data.get("joue")),
            titre=str(data.get("titre") or ""),
            artiste=str(data.get("artiste") or ""),
            url=str(data.get("url") or ""),
            accuses=[a for a in accuses[:_MAX_ACCUSES] if isinstance(a, dict)],
        )
    except Exception as exc:  # noqa: BLE001 — l'extension ne doit jamais voir un 500
        logger.error("Musique : battement en erreur : {e}", e=exc)
        return {"ordres": []}
    return {"ordres": ordres}


@public_router.get("/extension-musique.zip")
async def telecharger_extension() -> Response:
    """L'extension à installer chez Azraël, empaquetée à la volée.

    Publique par nécessité : Azraël n'a pas de compte sur ce dashboard et n'a pas
    accès au dépôt. Sans danger, et c'est une PROPRIÉTÉ à tenir — l'extension ne
    contient aucun secret, le jeton étant saisi par lui dans sa fenêtre de
    réglages. Un test le vérifie fichier par fichier.

    Construite à chaque appel plutôt que déposée une fois : un zip figé se
    périme à la première correction, et on enverrait alors une vieille version
    sans le savoir.
    """
    if not _EXTENSION_DIR.is_dir():
        raise HTTPException(404, "Extension introuvable sur ce déploiement")
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zf:
        for chemin in sorted(_EXTENSION_DIR.iterdir()):
            # Fichiers du dossier seulement : pas de récursion, il n'y a pas de
            # sous-dossier, et une descente aveugle emporterait un jour ce que
            # quelqu'un y aura déposé.
            if chemin.is_file() and not chemin.name.startswith("."):
                zf.write(chemin, chemin.name)
    logger.info("Extension musique téléchargée ({o} octets)", o=tampon.tell())
    return Response(
        content=tampon.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="wally-musique.zip"'},
    )
