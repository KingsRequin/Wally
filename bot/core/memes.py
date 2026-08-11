"""Memes de la communauté — images déposées à la main, affichées sur l'overlay.

Le dossier est relu à chaque tirage plutôt que mis en cache : l'owner y dépose
des fichiers quand il veut, et redémarrer le bot pour qu'une image apparaisse
serait absurde.

Wally ne VOIT pas ces images. Sa seule prise dessus est la description — nom du
fichier, ou fichier texte du même nom. C'est ce qui lui permet de choisir un
meme à propos plutôt qu'au hasard.
"""
from __future__ import annotations

import random
import unicodedata
from pathlib import Path

from loguru import logger

# Extension acceptée -> type MIME annoncé par la route publique. On ne laisse
# PAS `mimetypes` deviner : l'image Docker (Python 3.12, sans /etc/mime.types)
# ignore `.webp`, et les memes de ce format partaient en
# `application/octet-stream`. Ils s'affichent quand même — le navigateur renifle
# le contenu d'un `<img>` — mais rien ne le garantit, et le dossier compte déjà
# seize webp.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

# Ce que Wally peut MONTRER. Il affiche dans une balise `<img>` : une vidéo y
# serait cassée. `list()` s'y tient, et un test le vérifie.
_EXTENSIONS = frozenset(
    e for e, t in _MEDIA_TYPES.items() if t.startswith("image/")
)

# Ce que la route publique peut SERVIR. Servir un fichier ne demande pas de
# savoir l'afficher : le rotateur, lui, sait jouer les vidéos.
_EXTENSIONS_MEDIA = frozenset(_MEDIA_TYPES)


def media_type(path: Path) -> str:
    """Type MIME d'un meme, déduit de son extension."""
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")

# Au-delà, l'image met trop de temps à s'afficher : le widget serait passé avant
# d'être visible.
_MAX_BYTES = 8 * 1024 * 1024


def _describe(path: Path) -> str:
    """Description d'un meme : le .txt voisin s'il existe, sinon le nom du fichier.

    Deux formes de voisin, la première l'emporte :
    `chat.gif.txt` (extension complète) puis `chat.txt`. Sans la première,
    `chat.gif` et `chat.jpg` — deux images DIFFÉRENTES — se partageaient le seul
    `chat.txt` et héritaient de la même description : Wally en commentait une en
    décrivant l'autre. Dix paires du dossier étaient dans ce cas.
    """
    for sidecar in (path.with_name(path.name + ".txt"), path.with_suffix(".txt")):
        if not sidecar.is_file():
            continue
        try:
            # `errors="replace"` et non un try nu : un .txt écrit au Bloc-notes
            # Windows (cp1252) levait un UnicodeDecodeError — qui dérive de
            # ValueError, pas d'OSError — et `_describe` est appelé HORS du try
            # de `list()`. Un seul fichier mal encodé faisait tomber toute la
            # bibliothèque, pas seulement le fautif.
            text = sidecar.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return " ".join(text.split())[:160]
        except (OSError, ValueError):
            pass
    return " ".join(path.stem.replace("-", " ").replace("_", " ").split())[:160]


def _safe_name(name: str) -> str:
    """Nom de fichier réduit à sa forme sûre.

    Les images sont servies par une route publique : un nom venant de l'extérieur
    ne doit jamais pouvoir remonter l'arborescence.
    """
    return Path(unicodedata.normalize("NFC", name or "")).name


class MemeLibrary:
    """Inventaire du dossier de memes, et tirage sans répétition immédiate."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._last: str | None = None

    @property
    def directory(self) -> Path:
        return self._dir

    def list(self) -> list[dict]:
        """Memes disponibles, triés par nom. Liste vide si le dossier manque."""
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        out: list[dict] = []
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in _EXTENSIONS:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    logger.debug("Meme ignoré (trop lourd) : {n}", n=path.name)
                    continue
            except OSError:
                continue
            out.append({"name": path.name, "description": _describe(path)})
        return out

    def list_medias(self) -> list[dict]:
        """Images ET vidéos, chacune avec son genre. Pour le rotateur.

        Séparée de `list()` à dessein : celle-ci alimente une page qui sait
        jouer une vidéo, celle-là un `<img>` qui ne le sait pas.
        """
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        out: list[dict] = []
        for path in entries:
            suffix = path.suffix.lower()
            if not path.is_file() or suffix not in _EXTENSIONS_MEDIA:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    logger.debug("Média ignoré (trop lourd) : {n}", n=path.name)
                    continue
            except OSError:
                continue
            genre = "video" if _MEDIA_TYPES[suffix].startswith("video/") else "image"
            out.append({"name": path.name, "genre": genre})
        return out

    def pick(self, hint: str = "") -> dict | None:
        """Choisit un meme. `hint` privilégie ceux dont la description colle.

        Sans indice, tirage au sort en évitant le dernier montré : deux fois le
        même d'affilée passerait pour un bug.
        """
        memes = self.list()
        if not memes:
            return None
        hint = (hint or "").strip().lower()
        if hint:
            # On garde les MEILLEURS, pas tous ceux qui ont un mot en commun.
            # `any()` suffisait à retenir un meme, or « qui », « pas », « une »
            # passent le filtre de longueur et figurent dans presque toutes les
            # descriptions : « chat qui hurle » retenait donc quasi tout le
            # dossier et retombait sur un tirage au hasard. Compter les mots
            # trouvés fait remonter celui qui parle vraiment du sujet, sans
            # avoir à maintenir une liste de mots vides.
            words = {w for w in hint.split() if len(w) > 2}
            scored = [
                (sum(1 for w in words if w in m["description"].lower()), m)
                for m in memes
            ]
            best = max((score for score, _ in scored), default=0)
            if best:
                memes = [m for score, m in scored if score == best]
        pool = [m for m in memes if m["name"] != self._last] or memes
        chosen = random.choice(pool)
        self._last = chosen["name"]
        return chosen

    def resolve(self, name: str) -> Path | None:
        """Chemin d'un média servi publiquement, ou None si le nom est invalide.

        Accepte les vidéos : servir un fichier ne demande pas de savoir
        l'afficher, et le rotateur en réclame.
        """
        safe = _safe_name(name)
        if not safe or Path(safe).suffix.lower() not in _EXTENSIONS_MEDIA:
            return None
        path = self._dir / safe
        try:
            # `path.resolve().parent` et non `path.parent.resolve()` : le second
            # ne teste rien (`_safe_name` a déjà réduit au basename, le parent
            # EST le dossier), alors que le premier suit les liens symboliques —
            # un lien déposé dans le dossier serait sinon servi tel quel par la
            # route publique.
            if not path.is_file() or path.resolve().parent != self._dir.resolve():
                return None
        except OSError:
            return None
        return path
