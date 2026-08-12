# bot/core/meme_import.py
"""Faire entrer une image dans la banque de memes.

Toute la logique d'import vit ici, hors de Discord : la commande contextuelle et
`scripts/rattraper_memes.py` n'en sont que deux appelants, et le module se teste
sans réseau ni bot.

La conversion WebP y a été déplacée depuis `scripts/convertir_memes_webp.py`,
qui l'importe désormais. Le piège qu'elle existe pour éviter : convertir un GIF
animé « à la Pillow » perd l'animation sur un fichier sur trois — la sortie ne
garde qu'une frame et pèse 99 % de moins, ce qui ressemble à s'y méprendre à une
réussite. Deux copies de cette garde finiraient par diverger.
"""
from __future__ import annotations

import hashlib
import re
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from PIL import Image, ImageSequence

from bot.core.memes import _EXTENSIONS, _EXTENSIONS_MEDIA, _MAX_BYTES

A_CONVERTIR = frozenset({".gif", ".png"})

# Une animation supporte le lossy sans qu'on le voie — c'est ce qui donne les
# 70 % de gain. Une image fixe de meme, c'est d'abord du texte : sans perte.
QUALITE_ANIMEE = 80

_NUMERO = re.compile(r"^meme(\d+)\.", re.IGNORECASE)

# Au-delà, on n'essaie même pas de convertir : le fichier ne pourra de toute
# façon pas descendre sous le plafond d'affichage.
MAX_TELECHARGEMENT = 16 * 1024 * 1024


@dataclass
class ResultatImport:
    """Ce qu'il est advenu d'une tentative d'import."""

    ok: bool
    nom: str = ""
    raison: str = ""
    doublon: str = ""
    converti: bool = False
    octets: int = 0


def convertir_si_avantageux(octets: bytes, suffixe: str) -> tuple[bytes, str]:
    """Rend `(octets, suffixe)` en WebP si l'échange fait gagner, tels quels sinon.

    Passe par des fichiers temporaires plutôt que de travailler en mémoire : la
    vérification relit le WebP écrit pour compter ses frames et lire leurs
    durées dans les chunks ANMF. La réécrire sur des octets, c'est reprendre une
    garde éprouvée pour rien.
    """
    if suffixe.lower() not in A_CONVERTIR:
        return octets, suffixe
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{suffixe}"
        dst = Path(tmp) / "dst.webp"
        src.write_bytes(octets)
        try:
            convertir(src, dst)
            if verifier_conversion(src, dst):
                return octets, suffixe
        except Exception as e:  # noqa: BLE001 — un format exotique ne fait pas échouer l'import
            logger.warning("conversion de {suffixe} échouée : {err}", suffixe=suffixe, err=e)
            return octets, suffixe
        return dst.read_bytes(), ".webp"


def importer(
    octets: bytes, suffixe: str, description: str, dossier: Path
) -> ResultatImport:
    """Range une image dans la banque. N'écrit rien si elle est refusée."""
    suffixe = suffixe.lower()
    if suffixe not in _EXTENSIONS_MEDIA:
        admis = " ".join(sorted(_EXTENSIONS_MEDIA))
        return ResultatImport(False, raison=f"format {suffixe} non admis — attendus : {admis}")
    if len(octets) > MAX_TELECHARGEMENT:
        return ResultatImport(
            False, raison=f"{len(octets) / 1e6:.1f} Mo — au-delà de la limite de téléchargement"
        )

    index = empreintes(dossier)
    depuis = index.get(hashlib.sha256(octets).hexdigest())
    if depuis:
        return ResultatImport(False, doublon=depuis, raison="déjà rangé")

    finaux, suffixe_final = convertir_si_avantageux(octets, suffixe)
    converti = suffixe_final != suffixe
    if converti:
        depuis = index.get(hashlib.sha256(finaux).hexdigest())
        if depuis:
            return ResultatImport(False, doublon=depuis, raison="déjà rangé")

    # Le plafond ne s'applique qu'à ce qui doit s'AFFICHER : une vidéo n'est
    # jamais tirée par `list()`, la borner sur ce critère n'aurait pas de sens.
    if suffixe_final in _EXTENSIONS and len(finaux) > _MAX_BYTES:
        return ResultatImport(
            False,
            raison=(
                f"{len(finaux) / 1e6:.1f} Mo après conversion, au-dessus du plafond de "
                f"{_MAX_BYTES / 1e6:.0f} Mo — il serait rangé puis jamais tiré"
            ),
        )

    nom = f"meme{prochain_numero(dossier)}{suffixe_final}"
    (dossier / nom).write_bytes(finaux)
    if description.strip():
        (dossier / f"{nom}.txt").write_text(description.strip(), encoding="utf-8")
    return ResultatImport(True, nom=nom, converti=converti, octets=len(finaux))


def prochain_numero(dossier: Path) -> int:
    """Le maximum trouvé plus un — jamais le premier trou.

    Les sidecars comptent : un `meme9.webp.txt` resté seul réserve le 9, sinon
    le numéro est réattribué et cette vieille description se retrouve collée à
    une image qui n'a rien à voir.
    """
    numeros = [
        int(m.group(1))
        for p in dossier.iterdir()
        if p.is_file() and (m := _NUMERO.match(p.name))
    ]
    return max(numeros, default=0) + 1


def empreintes(dossier: Path) -> dict[str, str]:
    """SHA-256 → nom, pour les médias du dossier. Les `.txt` sont ignorés."""
    index: dict[str, str] = {}
    for p in sorted(dossier.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS_MEDIA:
            continue
        index.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p.name)
    return index


def durees_gif(im: Image.Image) -> list[int]:
    return [f.info.get("duration", im.info.get("duration", 100))
            for f in ImageSequence.Iterator(im)]


def durees_webp(path: Path) -> list[int]:
    """Durée de chaque frame, lue dans les chunks ANMF du fichier.

    Pillow ne relit pas cette information (`frame.info["duration"]` vaut None à
    la lecture d'un WebP), et c'est justement ce qu'il faut vérifier : une
    animation reconstruite à la mauvaise cadence est un défaut invisible au
    comptage de frames.
    """
    data = path.read_bytes()
    out: list[int] = []
    i = 12  # après l'en-tête RIFF/WEBP
    while i + 8 <= len(data):
        fourcc = data[i:i + 4]
        taille = struct.unpack("<I", data[i + 4:i + 8])[0]
        if fourcc == b"ANMF":
            # ANMF : x(3) y(3) largeur(3) hauteur(3) durée(3) drapeaux(1)
            d = data[i + 20:i + 23]
            out.append(d[0] | d[1] << 8 | d[2] << 16)
        i += 8 + taille + (taille & 1)
    return out


def convertir(src: Path, dst: Path) -> None:
    im = Image.open(src)
    if getattr(im, "n_frames", 1) > 1:
        # Les frames sont aplaties une à une : passer l'image d'origine à
        # `save_all` laisse Pillow se débrouiller avec les modes de disposition
        # du GIF, et c'est là qu'il perd l'animation.
        frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
        frames[0].save(
            dst, "WEBP", save_all=True, append_images=frames[1:],
            duration=durees_gif(Image.open(src)), loop=im.info.get("loop", 0),
            quality=QUALITE_ANIMEE, method=4, minimize_size=True,
        )
        return
    transparent = im.mode in ("RGBA", "LA") or "transparency" in im.info
    im.convert("RGBA" if transparent else "RGB").save(
        dst, "WEBP", lossless=True, quality=100, method=4,
    )


def verifier_conversion(src: Path, dst: Path) -> str:
    """Renvoie la raison du refus, ou une chaîne vide si la copie est fidèle.

    Sur une animation, on compare la DURÉE TOTALE et non la liste des frames :
    l'encodeur fusionne légitimement deux frames identiques qui se suivent (une
    de 50 ms et une de 150 ms deviennent une de 200 ms), ce qui ne change rien à
    ce qu'on voit. Exiger l'égalité stricte refusait ces fichiers-là ; la durée
    totale, elle, s'effondre dès que l'animation est vraiment perdue.
    """
    avant, apres = Image.open(src), Image.open(dst)
    if avant.size != apres.size:
        return f"taille {avant.size} devenue {apres.size}"
    if getattr(avant, "n_frames", 1) > 1:
        if getattr(apres, "n_frames", 1) < 2:
            return "animation perdue (une seule frame)"
        attendu, obtenu = sum(durees_gif(avant)), sum(durees_webp(dst))
        if attendu != obtenu:
            return f"animation de {attendu} ms devenue {obtenu} ms"
    poids = dst.stat().st_size
    if poids >= src.stat().st_size:
        return "plus lourd que l'original"
    if poids > _MAX_BYTES:
        return f"toujours au-dessus du plafond ({poids / 1e6:.1f} Mo)"
    return ""


def sidecar_de(path: Path) -> Path | None:
    """Le `.txt` collé à l'extension, s'il existe.

    La forme sans extension (`meme1.txt`) suit le nom de base et survit à la
    conversion : rien à faire pour elle.
    """
    voisin = path.with_name(path.name + ".txt")
    return voisin if voisin.is_file() else None
