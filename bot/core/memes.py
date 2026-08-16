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
from math import ceil
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
# d'être visible. S'applique à TOUT média servi — le rotateur joue les vidéos,
# et `list_medias()` les écarte au même plafond que les images.
_MAX_BYTES = 8 * 1024 * 1024

# Ce qu'une description peut peser. La lecture coupait à 160 sans que personne
# ne le sache côté écriture : `meme80.webp.txt` faisait 163 caractères et se
# terminait sur « SORT SON SKIN BL ». Une seule valeur, partagée par le lecteur
# (`_describe`), par l'import (`meme_import.importer`) et par le formulaire de
# la commande Discord — sinon la chaîne recommence à diverger.
MAX_DESCRIPTION = 160


def tronquer_description(texte: str) -> str:
    """Description mise à plat et ramenée à `MAX_DESCRIPTION`, sans couper un mot.

    Le mot entier ou rien : « SORT SON SKIN BL » est pire qu'une phrase plus
    courte — Wally lit cette description à voix haute quand il montre le meme.
    """
    plat = " ".join((texte or "").split())
    if len(plat) <= MAX_DESCRIPTION:
        return plat
    coupe = plat[:MAX_DESCRIPTION]
    espace = coupe.rfind(" ")
    return (coupe[:espace] if espace > 0 else coupe).rstrip(" ,;:")

# `list` est AUSSI le nom d'une méthode de `MemeLibrary`. Dans le corps de la
# classe, une méthode définie après elle et annotée `-> list[dict]` résout vers
# la méthode, pas vers le type — mypy le refuse. L'alias supprime le piège pour
# toutes les méthodes, quel que soit leur ordre.
_Entrees = list[dict]


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
                return tronquer_description(text)
        except (OSError, ValueError):
            pass
    return tronquer_description(path.stem.replace("-", " ").replace("_", " "))


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

    def list(self) -> _Entrees:
        """Memes disponibles, triés par nom. Liste vide si le dossier manque."""
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        out: _Entrees = []
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

    def list_medias(self) -> _Entrees:
        """Images ET vidéos, chacune avec son genre. Pour le rotateur.

        Séparée de `list()` à dessein : celle-ci alimente une page qui sait
        jouer une vidéo, celle-là un `<img>` qui ne le sait pas.
        """
        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            return []
        out: _Entrees = []
        for path in entries:
            suffix = path.suffix.lower()
            if not path.is_file() or suffix not in _EXTENSIONS_MEDIA:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    logger.debug("Média ignoré (trop lourd) : {n}", n=path.name)
                    continue
            # Le fichier a disparu entre `iterdir()` et `stat()` : l'owner range
            # son dossier pendant qu'on le lit. Le sauter est la bonne réponse —
            # journaliser ferait du bruit à chaque ménage, et lever priverait le
            # rotateur de TOUS les autres médias.
            except OSError:
                continue
            genre = "video" if _MEDIA_TYPES[suffix].startswith("video/") else "image"
            out.append({"name": path.name, "genre": genre})
        return out

    def enveloppe_rendue(self, media_max: int,
                         agrandir: float = 1.0) -> tuple[int, int] | None:
        """La place que les memes peuvent occuper à l'écran, au maximum.

        LA RÈGLE, dans les mots de l'owner : « prends la plus grande image en
        hauteur et la plus grande en largeur, et ça définit la box ». Appliquée
        aux FICHIERS elle est inapplicable — le dossier monte à 2100 × 2100,
        plus grand que le canvas. Appliquée aux tailles AFFICHÉES, elle est
        exacte : chaque meme est réduit pour tenir dans `media_max`, et
        l'enveloppe de ces tailles-là est la boîte qu'il faut réserver.

        Elle ne réserve donc que ce que le dossier peut vraiment atteindre. Un
        dossier sans portrait rendrait une boîte plus basse que large, sans que
        personne n'ait à retoucher un chiffre — c'est tout l'intérêt de la
        calculer plutôt que de l'écrire.

        `agrandir` : les petits memes sont grossis jusqu'à ce facteur pour ne pas
        paraître perdus (le rotateur le fait, à 2×). Il compte dans l'enveloppe,
        sinon la boîte serait trop étroite pour eux.

        Rend `None` si rien n'est mesurable — l'appelant garde alors sa table.
        Les vidéos ne le sont pas sans décodeur : elles ne comptent pas ici, et
        c'est sans danger, la boîte les borne à leur tour (`max-width: 100%`).
        """
        if media_max <= 0:
            return None
        try:
            from PIL import Image
        except ImportError:      # pragma: no cover - Pillow est une dépendance
            return None
        largeur = hauteur = 0.0
        for entree in self.list_medias():
            if entree.get("genre") != "image":
                continue
            chemin = self._dir / str(entree["name"])
            try:
                with Image.open(chemin) as im:
                    l, h = im.size
            # Fichier tronqué, format exotique, disparu pendant le ménage : un
            # meme illisible ne doit pas priver les autres de leur boîte.
            except Exception:
                continue
            if l <= 0 or h <= 0:
                continue
            facteur = min(media_max / l, media_max / h, agrandir)
            largeur = max(largeur, l * facteur)
            hauteur = max(hauteur, h * facteur)
        if largeur <= 0 or hauteur <= 0:
            return None
        # Arrondi au SUPÉRIEUR : un pixel de moins que le contenu, et le meme le
        # plus large déborderait de la boîte censée le contenir.
        return (min(media_max, ceil(largeur)), min(media_max, ceil(hauteur)))

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
