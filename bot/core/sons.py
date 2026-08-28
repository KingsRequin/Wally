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

import json
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

# Les moments du spectacle. Sert aussi de garde : la route publique reçoit le
# genre depuis l'URL, et tout ce qui n'est pas dans cette liste est refusé avant
# de toucher au disque.
#
# `raid/` sonne UNE fois, à l'instant où des inconnus débarquent. Le dossier est
# livré vide à la demande de l'owner (2026-08-21, « configurable, pas de son
# pour le moment ») : dossier absent ou vide, la fête est simplement muette —
# le jour où un fichier y est déposé, il sonne sans rebuild.
# `commande/` est le seul genre APPELABLE par un viewer : un fichier déposé là
# devient une commande de chat portant son propre nom (`apero.mp3` → `!apero`).
# Rien à déclarer ailleurs, comme pour les memes — l'owner dépose, ça marche.
GENRES = ("popup", "bsod", "raid", "commande")

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

    def commandes(self) -> dict[str, str]:
        """{nom de commande → nom de fichier} pour le genre `commande`.

        Le nom de la commande EST le nom du fichier, sans extension et en
        minuscules : `APERO.mp3` répond à `!apero`. Pas de table à tenir en
        parallèle du dossier — une table se désynchronise, un nom de fichier
        non.

        Deux fichiers de même nom à l'extension près (`apero.mp3` et
        `apero.wav`) : le premier dans l'ordre alphabétique gagne, et l'autre
        est simplement inatteignable. Le cas ne mérite pas d'erreur, mais il
        mérite de ne pas être silencieux côté panneau — d'où le tri stable.
        """
        return {Path(nom).stem.lower(): nom for nom in reversed(self.list("commande"))}

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


# Réglages par son : le fichier vit DANS le dossier des sons, pas dans
# `config.yaml`. Une sauvegarde du dossier emporte alors les réglages avec les
# fichiers, et un son supprimé n'a pas à être nettoyé à deux endroits.
_REGLAGES = "reglages.json"

# Aucun cooldown par défaut (arbitrage owner du 2026-08-28) : PhantomBot en
# imposait 120 s à tous, ce qui n'a jamais été demandé. Chaque son porte le
# sien, réglé au cas par cas depuis le panneau.
DEFAUTS: dict[str, float] = {"cooldown": 0.0, "volume": 1.0}


class ReglagesSons:
    """Cooldown et volume de chaque son de commande.

    Relu à CHAQUE demande, comme le dossier lui-même : l'owner règle un volume
    pendant le live et le son suivant doit en tenir compte, sans redémarrage.
    Un fichier absent ou illisible rend les défauts — un réglage perdu vaut
    mieux qu'un overlay muet.

    LECTURE seule pour l'instant : le fichier s'édite à la main. L'écriture
    arrivera avec l'écran qui l'appelle, jamais avant — un `ecrire()` sans
    appelant est le « bouton branché sur rien » que ce dépôt s'interdit.
    """

    def __init__(self, directory: str | Path) -> None:
        self._path = Path(directory) / "commande" / _REGLAGES

    def tout(self) -> dict[str, dict[str, float]]:
        try:
            brut = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(brut, dict):
            return {}
        return {str(k).lower(): v for k, v in brut.items() if isinstance(v, dict)}

    def pour(self, commande: str) -> dict[str, float]:
        """Les réglages d'un son, défauts compris. Jamais de clé manquante."""
        garde = dict(DEFAUTS)
        garde.update({
            k: float(v) for k, v in self.tout().get(commande.lower(), {}).items()
            if k in DEFAUTS and isinstance(v, (int, float))
        })
        garde["cooldown"] = max(0.0, garde["cooldown"])
        # Le volume est un MULTIPLICATEUR appliqué à la lecture. Plafonné à 2 :
        # au-delà, Web Audio sature et le son part en grésillement, ce qui
        # s'entend comme une panne du bot plutôt que comme un réglage.
        garde["volume"] = min(2.0, max(0.0, garde["volume"]))
        return garde
