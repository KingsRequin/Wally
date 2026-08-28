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

from loguru import logger

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
    """Cooldown, volume et alias de chaque son de commande.

    Relu à CHAQUE demande, comme le dossier lui-même : l'owner règle un volume
    pendant le live et le son suivant doit en tenir compte, sans redémarrage.
    Un fichier absent ou illisible rend les défauts — un réglage perdu vaut
    mieux qu'un overlay muet.

    L'écriture n'existe que depuis que l'atelier de Système → Overlay l'appelle
    (`PUT /api/admin/overlay/sons/{commande}`) — un `ecrire()` sans écran serait
    le « bouton branché sur rien » que ce dépôt s'interdit.
    """

    def __init__(self, directory: str | Path) -> None:
        self._path = Path(directory) / "commande" / _REGLAGES

    def tout(self) -> dict[str, dict]:
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

    def alias(self) -> dict[str, str]:
        """{autre nom → commande}. Ce que le chat tape VRAIMENT, en somme.

        Relevé dans les logs de PhantomBot : `!perk` a été tapé 8 fois et
        `!annif` 6 fois, pour des sons qui s'appellent `perks` et `anniv`. Ces
        gens-là n'ont rien entendu, et rien ne le leur a dit.

        Deux sons revendiquant le même alias : le premier dans l'ordre
        alphabétique gagne. Arbitraire, mais STABLE — un tri sur un dict au
        hasard ferait répondre un son différent selon le redémarrage, ce qui est
        indébogable depuis le chat.
        """
        out: dict[str, str] = {}
        for commande in sorted(self.tout()):
            noms = self.tout().get(commande, {}).get("alias") or []
            if not isinstance(noms, list):
                continue
            for nom in noms:
                if isinstance(nom, str) and nom.strip():
                    out.setdefault(nom.strip().lower(), commande)
        return out


    def ecrire(self, commande: str, valeurs: dict) -> dict:
        """Range cooldown, volume et alias d'un son, et rend ce qui a été retenu.

        Réécrit le fichier ENTIER à chaque fois, comme `config.save()` : deux
        onglets ouverts sur le panneau ne peuvent pas produire un JSON à moitié
        d'une version et à moitié de l'autre.
        """
        commande = commande.lower()
        courant = self.tout()
        entree = dict(courant.get(commande) or {})
        for cle in DEFAUTS:
            if isinstance(valeurs.get(cle), (int, float)):
                entree[cle] = float(valeurs[cle])
        if isinstance(valeurs.get("alias"), list):
            # Dédoublonné en gardant l'ordre de saisie : l'owner relit sa liste
            # telle qu'il l'a tapée, et un doublon ne fait rien de plus.
            propres: list[str] = []
            for nom in valeurs["alias"]:
                nom = str(nom).strip().lower()
                # Un alias qui porte le nom de sa propre commande ne sert à
                # rien et ferait croire à une deuxième porte.
                if nom and nom != commande and nom not in propres:
                    propres.append(nom)
            entree["alias"] = propres
        courant[commande] = entree
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(courant, indent=2, ensure_ascii=False),
                              encoding="utf-8")
        return {**self.pour(commande), "alias": entree.get("alias", [])}

    def oublier(self, commande: str) -> None:
        """Retire les réglages d'un son — appelé quand son fichier est supprimé.

        Sans ça, un `reglages.json` accumule les entrées de sons disparus, et un
        alias orphelin resterait affiché dans le panneau pour un son inexistant.
        """
        courant = self.tout()
        if courant.pop(commande.lower(), None) is None:
            return
        self._path.write_text(json.dumps(courant, indent=2, ensure_ascii=False),
                              encoding="utf-8")


def resoudre_commande(library: "SoundLibrary", reglages: ReglagesSons,
                      mot: str) -> tuple[str, str] | None:
    """(commande canonique, fichier) que ce mot déclenche, ou None.

    Les FICHIERS priment sur les alias, toujours. Sinon un alias posé par
    inadvertance — `"alias": ["mood"]` sur un son quelconque — détournerait un
    son existant, et le seul symptôme serait « le mauvais son sort », sans rien
    dans les logs pour dire pourquoi.

    Le couple rendu porte la commande CANONIQUE, pas le mot tapé : c'est elle
    qui porte le cooldown et le volume. Autrement, `!perk` contournerait
    tranquillement le cooldown de `!perks`.
    """
    mot = mot.strip().lower()
    fichiers = library.commandes()
    if mot in fichiers:
        return mot, fichiers[mot]
    canonique = reglages.alias().get(mot)
    if canonique and canonique in fichiers:
        return canonique, fichiers[canonique]
    return None


# ── Normalisation ─────────────────────────────────────────────────────────────
#
# Sept fichiers déposés au fil des ans, sept niveaux différents : `!apero` couvre
# le jeu quand `!rina` s'entend à peine. `loudnorm` (EBU R128) les met au même
# niveau PERÇU — pas au même pic, ce qui ne veut rien dire à l'oreille.
#
# ffmpeg est déjà dans l'image (7.1.5) : aucune dépendance à ajouter. Les valeurs
# viennent du `normalise_mp3.sh` de PhantomBot, qui faisait le même travail à la
# main dans un GUI tkinter.
_LUFS_CIBLE = -14.0
_TRUE_PEAK = -1.5

# L'original est mis de côté avant traitement (arbitrage owner) : une
# normalisation ratée ne doit pas coûter le son. Suffixe et non sous-dossier —
# `list()` ignore déjà tout ce qui n'a pas une extension audio.
SUFFIXE_ORIGINAL = ".origine"


def normaliser(chemin: Path, *, timeout: float = 120.0) -> bool:
    """Met un son au niveau perçu de référence. Rend True si le fichier a changé.

    BLOQUANT (ffmpeg) : à appeler dans `asyncio.to_thread`, jamais dans la
    boucle d'événements.

    Le fichier n'est remplacé qu'une fois ffmpeg terminé SANS erreur et avec une
    sortie non vide. Un ffmpeg tué par le timeout laissait sinon un mp3 tronqué
    à la place d'un son qui marchait.
    """
    import shutil
    import subprocess
    import tempfile

    if not chemin.is_file():
        return False
    garde = chemin.with_suffix(chemin.suffix + SUFFIXE_ORIGINAL)
    with tempfile.NamedTemporaryFile(suffix=chemin.suffix, delete=False) as tmp:
        sortie = Path(tmp.name)
    try:
        res = subprocess.run(
            ["ffmpeg", "-y", "-i", str(chemin),
             "-af", f"loudnorm=I={_LUFS_CIBLE}:TP={_TRUE_PEAK}:LRA=11",
             "-c:a", "libmp3lame", "-q:a", "2", str(sortie)],
            capture_output=True, timeout=timeout, check=False,
        )
        if res.returncode != 0 or sortie.stat().st_size == 0:
            logger.warning("Normalisation de {f} échouée : {e}", f=chemin.name,
                           e=res.stderr.decode("utf-8", "replace")[-300:])
            return False
        # L'original n'est gardé QUE la première fois : normaliser deux fois ne
        # doit pas écraser la sauvegarde par une version déjà traitée.
        if not garde.exists():
            shutil.copy2(chemin, garde)
        shutil.move(str(sortie), str(chemin))
        logger.info("Son normalisé : {f}", f=chemin.name)
        return True
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Normalisation de {f} impossible : {e!r}", f=chemin.name, e=e)
        return False
    finally:
        sortie.unlink(missing_ok=True)
