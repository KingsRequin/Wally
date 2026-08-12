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

import struct
from pathlib import Path

from PIL import Image, ImageSequence

from bot.core.memes import _MAX_BYTES

A_CONVERTIR = frozenset({".gif", ".png"})

# Une animation supporte le lossy sans qu'on le voie — c'est ce qui donne les
# 70 % de gain. Une image fixe de meme, c'est d'abord du texte : sans perte.
QUALITE_ANIMEE = 80


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
