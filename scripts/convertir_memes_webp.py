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
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Les fonctions vivaient ici ; elles sont désormais partagées avec la commande
# Discord qui range un meme. Une seule garde anti-perte d'animation.
from bot.core.meme_import import (
    A_CONVERTIR,
    convertir,
    sidecar_de,
    verifier_conversion,
)


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
        if not src.is_file() or src.suffix.lower() not in A_CONVERTIR:
            continue
        dst = src.with_suffix(".webp")
        if dst.exists():
            refuses.append(f"{src.name} : {dst.name} existe déjà")
            continue
        try:
            convertir(src, dst)
            probleme = verifier_conversion(src, dst)
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
            txt = sidecar_de(src)
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
