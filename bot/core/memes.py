"""Memes de la communauté — images déposées à la main, affichées sur l'overlay.

Le dossier est relu à chaque tirage plutôt que mis en cache : l'owner y dépose
des fichiers quand il veut, et redémarrer le bot pour qu'une image apparaisse
serait absurde.

Wally ne VOIT pas ces images. Sa seule prise dessus est la description — nom du
fichier, ou fichier texte du même nom. C'est ce qui lui permet de choisir un
meme à propos plutôt qu'au hasard.
"""
from __future__ import annotations

import os
import random
import re
import sqlite3
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
_Termes = list[str]


def chemin_description(path: Path) -> Path:
    """Le sidecar CANONIQUE d'un meme : `chat.gif.txt`, collé à l'extension.

    Celui qu'on écrit, et celui que `description_ecrite` lit en premier. La
    forme sans extension (`chat.txt`) se lit encore — le dossier en compte —
    mais ne s'écrit plus : `chat.gif` et `chat.jpg` la partageaient et
    héritaient de la même phrase.
    """
    return path.with_name(path.name + ".txt")


def description_ecrite(path: Path) -> str:
    """La description ÉCRITE sur ce meme, ou "" si personne n'en a écrit.

    Deux formes de voisin, la première l'emporte : `chat.gif.txt` puis
    `chat.txt`. Le repli sur le nom du fichier n'est PAS fait ici — l'écran
    d'édition doit pouvoir distinguer « décrit » de « nommé », sans quoi il
    proposerait « meme80 » comme une phrase à corriger.
    """
    for sidecar in (chemin_description(path), path.with_suffix(".txt")):
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
        # Un sidecar illisible ou mal encodé ne vaut pas mieux qu'aucun sidecar :
        # on retombe sur le nom du fichier, juste en dessous. C'est un REPLI, pas
        # un silence — il y a toujours une description au bout.
        except (OSError, ValueError):
            pass
    return ""


def ecrire_description(path: Path, texte: str) -> str:
    """Écrit la description d'un meme, ou l'efface si `texte` est vide.

    Rend ce que Wally lira ENSUITE — pas ce qu'on vient d'écrire. Les deux
    diffèrent dans deux cas que l'écran doit montrer sans mentir : une phrase
    trop longue est ramenée à `MAX_DESCRIPTION`, et une description effacée
    peut redécouvrir un vieux `chat.txt` partagé, qui reprend alors la main.
    """
    sidecar = chemin_description(path)
    retenu = tronquer_description(texte)
    if retenu:
        sidecar.write_text(retenu, encoding="utf-8")
    else:
        sidecar.unlink(missing_ok=True)
    return _describe(path)


def _describe(path: Path) -> str:
    """Description d'un meme : ce qui est écrit, sinon le nom du fichier."""
    return description_ecrite(path) or tronquer_description(
        path.stem.replace("-", " ").replace("_", " ")
    )


# ── Recherche ──
#
# Le tirage par indice comptait les mots de plus de DEUX lettres trouvés dans
# la description. « sur », « les », « qui », « une » en font trois et vivent
# dans presque toutes les phrases françaises : ils marquaient un point partout,
# et le meme qui parlait VRAIMENT du sujet — un seul point — tombait hors du
# lot retenu. « le meme sur les cheaters » ne pouvait donc littéralement jamais
# sortir le meme sur les cheaters. Mesuré sur les 172 memes de prod le
# 2026-08-31 : `les` 23 %, `sur` 22 %, `qui` 34 % des descriptions.
#
# BM25 règle ça sans liste de mots vides à tenir à jour : un terme pèse à
# l'inverse de sa fréquence, donc `les` s'annule tout seul, et d'autant mieux
# que la réserve grandit.

# Part des mots de la demande qui peut manquer à TOUTE la réserve avant qu'on
# avoue ne pas avoir le meme. C'est l'absence, pas la rareté, qui dit « je n'ai
# pas ça » : `rose` et `costume` sont rares ET présents, donc un seuil de rareté
# acceptait « licorne rose » et « des dinosaures en costume ». Le mot introuvable,
# lui, tranche — et sans dépendre de la taille du dossier, contrairement à une
# fréquence relative, qui ne veut plus rien dire sur une réserve de cinq memes.
#
# Mesuré sur les 172 memes de prod le 2026-08-31 : douze demandes légitimes
# (`cheaters`, `aim assist`, `la manette`, `give up`…) sont toutes à 0 % de mots
# introuvables ; sept hors-sujets (`licorne rose`, `le tricot`, `le championnat
# de curling`…) sont tous à 25 % ou plus. La marge est franche.
_INTROUVABLES_MAX = 0.25

# En dessous de cette taille, l'absence d'un mot ne prouve rien : une petite
# réserve ne contient même pas le vocabulaire courant, et « les cheaters » se
# ferait refuser parce que `les` manque, pas parce que le sujet manque. Mesuré
# en tirant des sous-ensembles du dossier de prod : sur vingt mots français très
# courants, il en manque 6,5 à cinq memes, 2,8 à dix, 1,0 à vingt, et 0,1 à
# trente. En dessous, on classe et on montre — comme avant.
_RESERVE_JUGEABLE = 30

# Au-delà de ce rapport au meilleur score, on ne parle plus du même sujet. Sert
# la VARIÉTÉ, pas la pertinence : entre deux memes également à propos, on tire.
_ECART_MAX = 1.25

_MOT = re.compile(r"[0-9a-z]+")


def _termes(texte: str) -> _Termes:
    """Mots cherchables d'un texte : sans accent, sans casse, sans ponctuation.

    Le dépliage des accents double celui du tokenizer FTS5 (`remove_diacritics`)
    au lieu de s'y fier : la requête est découpée ICI, et `[0-9a-z]+` sur du
    texte accentué couperait « équipe » en « quipe ».
    """
    plat = unicodedata.normalize("NFKD", (texte or "").lower())
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return [m.group() for m in _MOT.finditer(plat) if len(m.group()) > 1]


def _safe_name(name: str) -> str:
    """Nom de fichier réduit à sa forme sûre.

    Les images sont servies par une route publique : un nom venant de l'extérieur
    ne doit jamais pouvoir remonter l'arborescence.
    """
    return Path(unicodedata.normalize("NFC", name or "")).name


def enveloppe_images(chemins, media_max: int,
                     agrandir: float = 1.0) -> tuple[int, int] | None:
    """La place que ces images peuvent occuper à l'écran, au maximum.

    LA RÈGLE, dans les mots de l'owner : « prends la plus grande image en
    hauteur et la plus grande en largeur, et ça définit la box ». Appliquée aux
    FICHIERS elle est inapplicable — le dossier de memes monte à 2100 × 2100,
    plus grand que le canvas. Appliquée aux tailles AFFICHÉES, elle est exacte :
    chaque image est réduite pour tenir dans `media_max`, et l'enveloppe de ces
    tailles-là est la boîte qu'il faut réserver.

    Elle ne réserve donc que ce que le dossier peut vraiment atteindre. Un
    dossier sans portrait rend une boîte plus basse que large, sans que personne
    n'ait à retoucher un chiffre — c'est tout l'intérêt de la calculer plutôt
    que de l'écrire. Un cadre écrit à la main est un cadre faux le jour où le
    contenu change, et personne ne le remarque.

    `agrandir` : les petites images sont grossies jusqu'à ce facteur pour ne pas
    paraître perdues (le rotateur de memes le fait, à 2×). Il compte dans
    l'enveloppe, sinon la boîte serait trop étroite pour elles.

    Rend `None` si rien n'est mesurable — l'appelant garde alors sa table.
    """
    if media_max <= 0:
        return None
    try:
        from PIL import Image
    except ImportError:      # pragma: no cover - Pillow est une dépendance
        return None
    largeur = hauteur = 0.0
    for chemin in chemins:
        try:
            with Image.open(chemin) as im:
                l, h = im.size
        # Fichier tronqué, format exotique, disparu pendant un ménage : une
        # image illisible ne doit pas priver les autres de leur boîte.
        except Exception:
            continue
        if l <= 0 or h <= 0:
            continue
        facteur = min(media_max / l, media_max / h, agrandir)
        largeur = max(largeur, l * facteur)
        hauteur = max(hauteur, h * facteur)
    if largeur <= 0 or hauteur <= 0:
        return None
    # Arrondi au SUPÉRIEUR : un pixel de moins que le contenu, et la plus grande
    # image déborderait de la boîte censée la contenir.
    return (min(media_max, ceil(largeur)), min(media_max, ceil(hauteur)))


class MemeLibrary:
    """Inventaire du dossier de memes, et tirage sans répétition immédiate."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._last: str | None = None
        # Index de recherche, reconstruit seulement quand le dossier bouge.
        self._index: sqlite3.Connection | None = None
        self._indexe: _Entrees = []
        self._signature: tuple | None = None

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
            # Un fichier illisible (permission, lien mort, disque) ne doit pas emporter
            # la bibliothèque entière : on saute CE meme et on continue. Le dossier est
            # relu à chaque tirage, l'owner y dépose des fichiers en direct — un état
            # transitoire y est normal, pas exceptionnel.
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
        images = [self._dir / str(e["name"]) for e in self.list_medias()
                  if e.get("genre") == "image"]
        return enveloppe_images(images, media_max, agrandir)

    def _signature_dossier(self) -> tuple | None:
        """Ce qui, dans le dossier, invaliderait l'index. None s'il est illisible.

        `scandir` et pas `list()` : à cinq cents memes, relire les cinq cents
        descriptions à chaque tirage ferait cinq cents `open()` synchrones dans
        la boucle d'événements, pour un dossier qui n'a presque jamais bougé.
        Le `stat` d'une entrée, lui, est déjà porté par le parcours.

        Les sidecars comptent autant que les images : une description corrigée
        depuis l'atelier ne change ni le nombre de fichiers ni leur nom.
        """
        try:
            with os.scandir(self._dir) as entrees:
                signature: list[tuple[str, int, int]] = []
                for entree in entrees:
                    if not entree.is_file():
                        continue
                    stat = entree.stat()
                    signature.append((entree.name, stat.st_mtime_ns, stat.st_size))
            return tuple(sorted(signature))
        # Dossier absent ou illisible : `list()` rend déjà [] dans ce cas, et
        # `pick()` en fait un None. Pas de cache à invalider, rien à dire de plus.
        except OSError:
            return None

    def _fermer_index(self) -> None:
        """Rend la connexion en cours. Sans ça, chaque dépôt de meme en laisse
        une derrière lui jusqu'au passage du ramasse-miettes."""
        if self._index is not None:
            self._index.close()
        self._index, self._indexe, self._signature = None, [], None

    def _index_a_jour(self) -> sqlite3.Connection | None:
        """L'index FTS5 du dossier, reconstruit s'il a bougé depuis la dernière fois.

        En mémoire, jamais sur disque : le dossier est la seule source de vérité,
        et un index persisté finirait par en diverger sans que rien ne le dise.
        Sur 172 memes la reconstruction coûte quelques millisecondes, très en
        dessous de la lecture des descriptions qu'elle accompagne.
        """
        signature = self._signature_dossier()
        if signature is None:
            self._fermer_index()
            return None
        if self._index is not None and signature == self._signature:
            return self._index
        entrees = self.list()
        # `check_same_thread=False` : l'index est construit au premier tirage,
        # dans le thread qui l'a demandé. Un `pick()` venu d'un `to_thread`
        # lèverait sinon une ProgrammingError — et Wally deviendrait muet sur les
        # memes sans qu'aucun test ne le voie. La base est en mémoire, jetable,
        # et n'est écrite qu'ici : il n'y a rien à corrompre.
        self._fermer_index()
        index = sqlite3.connect(":memory:", check_same_thread=False)
        index.execute(
            "CREATE VIRTUAL TABLE memes USING fts5("
            "nom UNINDEXED, texte, tokenize='unicode61 remove_diacritics 2')"
        )
        index.executemany(
            "INSERT INTO memes(nom, texte) VALUES (?, ?)",
            [(e["name"], e["description"]) for e in entrees],
        )
        self._index, self._indexe, self._signature = index, entrees, signature
        return index

    def _classer(self, index: sqlite3.Connection, termes: _Termes) -> _Entrees:
        """Les memes qui parlent du sujet, du plus au moins pertinent. [] si aucun.

        Rendre [] est une RÉPONSE, pas un échec : elle vaut « je n'ai pas ça »,
        et l'appelant la transforme en aveu plutôt qu'en meme au hasard.
        """
        if len(self._indexe) >= _RESERVE_JUGEABLE:
            introuvables = sum(
                1
                for terme in termes
                if not index.execute(
                    "SELECT 1 FROM memes WHERE memes MATCH ? LIMIT 1", (f'"{terme}"*',)
                ).fetchone()
            )
            if introuvables / len(termes) >= _INTROUVABLES_MAX:
                return []
        # Le mot exact ET son préfixe : le préfixe seul rattrape les pluriels et
        # les dérivés (« cheater » trouve « cheaters », « triche » « tricheur »),
        # mais il ramène aussi « chatouilles » pour « chat ». Chercher les deux
        # fait matcher DEUX clauses au document qui porte le mot entier contre une
        # seule au faux ami, et bm25 additionne : l'exact passe devant sans qu'on
        # perde le dérivé.
        requete = " OR ".join(
            f'("{t}" OR "{t}"*)' for t in dict.fromkeys(termes)
        )
        lignes = index.execute(
            "SELECT nom, bm25(memes) FROM memes WHERE memes MATCH ? ORDER BY 2",
            (requete,),
        ).fetchall()
        if not lignes:
            return []
        # bm25 est NÉGATIF, le plus petit gagne. On garde le peloton de tête pour
        # que deux memes également à propos ne donnent pas toujours le même.
        limite = lignes[0][1] / _ECART_MAX
        retenus = {nom for nom, score in lignes if score <= limite}
        return [e for e in self._indexe if e["name"] in retenus]

    def pick(self, hint: str = "") -> dict | None:
        """Choisit un meme. `hint` privilégie ceux dont la description colle.

        Sans indice, tirage au sort en évitant le dernier montré : deux fois le
        même d'affilée passerait pour un bug.

        Avec un indice dont le sujet est absent de la réserve, rend None — Wally
        dira qu'il ne l'a pas. Montrer autre chose et le commenter comme si
        c'était le bon ne trompait que les spectateurs.
        """
        index = self._index_a_jour()
        if index is None or not self._indexe:
            return None
        termes = _termes(hint)
        if termes:
            memes = self._classer(index, termes)
            if not memes:
                return None
        else:
            memes = self._indexe
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
