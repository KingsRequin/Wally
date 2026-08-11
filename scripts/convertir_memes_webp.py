#!/usr/bin/env python3
"""Convertit les memes GIF et PNG du dossier en WebP.

Pourquoi seulement ces deux formats : les GIF pèsent l'essentiel du dossier
(52 Mo pour 21 fichiers, jusqu'à 5 Mo l'unité) et un widget d'overlay passe en
quelques secondes — une image qui arrive après n'a jamais été vue. Les PNG y
gagnent aussi, sans perte. Les JPEG sont laissés tels quels : le gain absolu est
dérisoire et les recompresser abîmerait le texte des memes. Les autres fichiers
(dont le MP4, réservé à un autre overlay) ne sont pas touchés.

Le piège que ce script existe pour éviter : convertir un GIF animé « à la
Pillow » perd l'animation sur un fichier sur trois — la sortie ne garde qu'une
frame et pèse 99 % de moins, ce qui ressemble à s'y méprendre à une réussite.
Chaque conversion est donc relue et comparée à la source (taille, nombre de
frames, durée de chacune) ; au moindre écart le fichier est laissé intact.

Usage :
    python3 scripts/convertir_memes_webp.py                 # simulation
    python3 scripts/convertir_memes_webp.py --apply         # remplace vraiment
    python3 scripts/convertir_memes_webp.py --dossier data/memes --apply
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

from PIL import Image, ImageSequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importé plutôt que recopié : deux plafonds qui divergent, c'est un meme qui
# disparaît de la bibliothèque sans que personne ne comprenne pourquoi.
from bot.core.memes import _MAX_BYTES

_A_CONVERTIR = {".gif", ".png"}

# Une animation supporte le lossy sans qu'on le voie — c'est ce qui donne les
# 70 % de gain. Une image fixe de meme, c'est d'abord du texte : sans perte.
_QUALITE_ANIMEE = 80


def _durees_gif(im: Image.Image) -> list[int]:
    return [f.info.get("duration", im.info.get("duration", 100))
            for f in ImageSequence.Iterator(im)]


def _durees_webp(path: Path) -> list[int]:
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


def _convertir(src: Path, dst: Path) -> None:
    im = Image.open(src)
    if getattr(im, "n_frames", 1) > 1:
        # Les frames sont aplaties une à une : passer l'image d'origine à
        # `save_all` laisse Pillow se débrouiller avec les modes de disposition
        # du GIF, et c'est là qu'il perd l'animation.
        frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
        frames[0].save(
            dst, "WEBP", save_all=True, append_images=frames[1:],
            duration=_durees_gif(Image.open(src)), loop=im.info.get("loop", 0),
            quality=_QUALITE_ANIMEE, method=4, minimize_size=True,
        )
        return
    transparent = im.mode in ("RGBA", "LA") or "transparency" in im.info
    im.convert("RGBA" if transparent else "RGB").save(
        dst, "WEBP", lossless=True, quality=100, method=4,
    )


def _verifier(src: Path, dst: Path) -> str:
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
        attendu, obtenu = sum(_durees_gif(avant)), sum(_durees_webp(dst))
        if attendu != obtenu:
            return f"animation de {attendu} ms devenue {obtenu} ms"
    poids = dst.stat().st_size
    if poids >= src.stat().st_size:
        return "plus lourd que l'original"
    if poids > _MAX_BYTES:
        return f"toujours au-dessus du plafond ({poids / 1e6:.1f} Mo)"
    return ""


def _sidecar(path: Path) -> Path | None:
    """Le `.txt` collé à l'extension, s'il existe.

    La forme sans extension (`meme1.txt`) suit le nom de base et survit à la
    conversion : rien à faire pour elle.
    """
    voisin = path.with_name(path.name + ".txt")
    return voisin if voisin.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossier", default="data/memes")
    parser.add_argument("--apply", action="store_true",
                        help="remplace les fichiers ; sans lui, rien n'est écrit")
    args = parser.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}")
        return 1

    gagne = perdu = 0
    convertis: list[str] = []
    refuses: list[str] = []
    for src in sorted(dossier.iterdir()):
        if not src.is_file() or src.suffix.lower() not in _A_CONVERTIR:
            continue
        dst = src.with_suffix(".webp")
        if dst.exists():
            refuses.append(f"{src.name} : {dst.name} existe déjà")
            continue
        try:
            _convertir(src, dst)
            probleme = _verifier(src, dst)
        except Exception as exc:  # noqa: BLE001 — un format exotique ne doit rien interrompre
            dst.unlink(missing_ok=True)
            refuses.append(f"{src.name} : {exc}")
            continue
        if probleme:
            dst.unlink()
            refuses.append(f"{src.name} : {probleme}")
            continue

        avant, apres = src.stat().st_size, dst.stat().st_size
        gagne += avant
        perdu += apres
        convertis.append(f"{src.name:16} {avant / 1e6:6.2f} Mo -> {apres / 1e6:5.2f} Mo"
                         f"  ({100 - 100 * apres / avant:3.0f} %)")
        if args.apply:
            txt = _sidecar(src)
            if txt is not None:
                txt.rename(dst.with_name(dst.name + ".txt"))
            src.unlink()
        else:
            dst.unlink()

    for ligne in convertis:
        print(ligne)
    if refuses:
        print("\nLaissés intacts :")
        for ligne in refuses:
            print(f"  {ligne}")
    if convertis:
        print(f"\n{len(convertis)} fichiers : {gagne / 1e6:.1f} Mo -> {perdu / 1e6:.1f} Mo "
              f"({100 - 100 * perdu / gagne:.0f} % de gain)")
    if not args.apply:
        print("\nSimulation — rien n'a été écrit. Relancer avec --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
