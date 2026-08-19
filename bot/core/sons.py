"""Les sons de l'overlay — des fichiers déposés à la main, joués par la page.

Même parti pris que les memes : le dossier est relu à chaque demande plutôt que
gardé en mémoire. L'owner y dépose ce qu'il veut pendant le live, et redémarrer
le bot pour changer un ding serait absurde.

Deux tiroirs, parce que les deux moments n'ont rien à voir : `popup/` sonne à
CHAQUE fenêtre du spam de virus — des centaines en trente secondes — tandis que
`bsod/` ne sonne qu'une fois, sur l'écran bleu final. Un seul dossier mélangé
aurait fait tomber l'impact grave au milieu du spam.

Rien n'est écrit en dur ici : ni un nom de fichier, ni un nombre de sons. Ce
qui est dans le dossier est ce qui sonne.
"""
from __future__ import annotations

from pathlib import Path

from bot.core.memes import _safe_name

# Extension acceptée -> type MIME annoncé par la route publique. On ne laisse
# PAS `mimetypes` deviner : l'image Docker (Python 3.12, sans /etc/mime.types)
# a déjà rendu `application/octet-stream` sur les memes en webp. Un navigateur
# renifle le contenu, mais `decodeAudioData` reçoit un ArrayBuffer — autant
# annoncer juste.
_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}

# Les deux moments du spectacle. Sert aussi de garde : la route publique reçoit
# le genre depuis l'URL, et tout ce qui n'est pas dans cette liste est refusé
# avant de toucher au disque.
GENRES = ("popup", "bsod")

# Un ding, pas une bande-son. Au-delà, le décodage bloque la page du live le
# temps du chargement — et un son de plusieurs mégaoctets sur une fenêtre qui
# s'ouvre dix fois par seconde n'a de toute façon aucun sens.
_MAX_BYTES = 2 * 1024 * 1024


def media_type(path: Path) -> str:
    """Type MIME d'un son, déduit de son extension."""
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


class SoundLibrary:
    """Inventaire des sons de l'overlay, par genre."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    @property
    def directory(self) -> Path:
        return self._dir

    def list(self, genre: str) -> list[str]:
        """Noms des sons d'un genre, triés. Liste vide si le dossier manque.

        Ne lève jamais : un overlay muet vaut mieux qu'un overlay en erreur, et
        la page ne saurait pas distinguer un dossier absent d'une panne du bot.
        """
        if genre not in GENRES:
            return []
        try:
            entries = sorted((self._dir / genre).iterdir())
        except OSError:
            return []
        out: list[str] = []
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in _MEDIA_TYPES:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    continue
            # Fichier disparu entre l'inventaire et la mesure : l'owner range
            # son dossier pendant le live. Il n'est simplement pas dans la
            # liste, il n'y a rien à signaler.
            except OSError:
                continue
            out.append(path.name)
        return out

    def inventaire(self) -> dict[str, list[str]]:
        """Tous les genres d'un coup — ce que sert la route publique."""
        return {genre: self.list(genre) for genre in GENRES}

    def resolve(self, genre: str, name: str) -> Path | None:
        """Chemin d'un son servi publiquement, ou None si la demande est invalide.

        Seule barrière entre une URL publique et le disque, donc stricte : genre
        connu, nom réduit à son basename, extension attendue, et le fichier doit
        se trouver DANS le dossier une fois les liens symboliques suivis.
        """
        if genre not in GENRES:
            return None
        safe = _safe_name(name)
        if not safe or Path(safe).suffix.lower() not in _MEDIA_TYPES:
            return None
        dossier = self._dir / genre
        path = dossier / safe
        try:
            # `path.resolve().parent` et non `path.parent.resolve()` : le second
            # ne teste rien (le parent EST le dossier), alors que le premier
            # suit les liens symboliques — un lien déposé là serait sinon servi
            # tel quel par la route publique.
            if not path.is_file() or path.resolve().parent != dossier.resolve():
                return None
        except OSError:
            return None
        return path
