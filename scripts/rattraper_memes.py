#!/usr/bin/env python3
"""Rattrape la banque de memes : décrit les muets, convertit ce qui y gagne.

Les memes déposés à la main n'ont pas toujours de `.txt`. Leur description
retombe alors sur le nom du fichier — « meme80 » : `pick(hint)` cherchant dans
les descriptions, ils sont introuvables par mot-clé, et Wally les commente à
l'aveugle. Ceux déposés depuis la dernière conversion pèsent aussi dix fois leur
poids.

Ce script n'a pas de logique propre : il déroule `bot.core.meme_import` sur le
dossier. Ce que fait la commande Discord à l'unité, il le fait en série.

Usage :
    python3 scripts/rattraper_memes.py                  # simulation
    python3 scripts/rattraper_memes.py --apply          # écrit vraiment
    python3 scripts/rattraper_memes.py --apply --sans-decrire
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from bot.core import meme_import  # noqa: E402
from bot.core.memes import _MEDIA_TYPES  # noqa: E402


async def _decrire(chemin: Path) -> str:
    """Décrit un fichier LOCAL : il n'est pas en ligne, on l'envoie en base64."""
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.vision import VisionService

    class _Db:
        async def log_cost(self, **_):
            return None

    mime = _MEDIA_TYPES.get(chemin.suffix.lower(), "image/png")
    url = f"data:{mime};base64," + base64.b64encode(chemin.read_bytes()).decode()
    svc = VisionService(OpenAILLMClient(model="gpt-5-nano", db=_Db(), max_tokens=400))
    if not svc.available:
        return ""
    return await svc.analyze([url], prompt_name="meme_describe_system") or ""


def _convertir_dossier(dossier: Path, apply: bool) -> None:
    """La même garde que `convertir_memes_webp.py`, sur les fichiers restants.

    Seule la boucle de parcours est écrite ici : `convertir` et
    `verifier_conversion` viennent du module partagé, donc l'unique garde
    anti-perte d'animation reste unique.
    """
    gagne = perdu = 0
    for src in sorted(dossier.iterdir()):
        if not src.is_file() or src.suffix.lower() not in meme_import.A_CONVERTIR:
            continue
        dst = src.with_suffix(".webp")
        if dst.exists():
            print(f"  {src.name:16} laissé — {dst.name} existe déjà")
            continue
        try:
            meme_import.convertir(src, dst)
            probleme = meme_import.verifier_conversion(src, dst)
        except Exception as exc:  # noqa: BLE001 — un format exotique n'interrompt rien
            dst.unlink(missing_ok=True)
            print(f"  {src.name:16} laissé — {exc}")
            continue
        if probleme:
            dst.unlink()
            print(f"  {src.name:16} laissé — {probleme}")
            continue

        avant, apres = src.stat().st_size, dst.stat().st_size
        gagne, perdu = gagne + avant, perdu + apres
        print(f"  {src.name:16} {avant / 1e6:6.2f} Mo -> {apres / 1e6:5.2f} Mo"
              f"  ({100 - 100 * apres / avant:3.0f} %)")
        if apply:
            txt = meme_import.sidecar_de(src)
            if txt is not None:
                txt.rename(dst.with_name(dst.name + ".txt"))
            src.unlink()
        else:
            dst.unlink()
    if gagne:
        print(f"  → {gagne / 1e6:.1f} Mo deviennent {perdu / 1e6:.1f} Mo")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossier", default="data/memes")
    parser.add_argument("--apply", action="store_true",
                        help="écrit ; sans lui, rien n'est modifié")
    parser.add_argument("--sans-decrire", action="store_true",
                        help="ne fait que la conversion")
    args = parser.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}")
        return 1

    muets = meme_import.memes_sans_description(dossier)
    print(f"{len(muets)} meme(s) sans description")
    if not args.sans_decrire:
        for chemin in muets:
            if chemin.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                print(f"  {chemin.name:16} laissé — pas d'analyse possible sur une vidéo")
                continue
            texte = await _decrire(chemin)
            if not texte:
                print(f"  {chemin.name:16} aucune description obtenue")
                continue
            print(f"  {chemin.name:16} {texte[:90]}")
            if args.apply:
                chemin.with_name(chemin.name + ".txt").write_text(texte, encoding="utf-8")

    print("\nConversion en WebP :")
    _convertir_dossier(dossier, args.apply)

    if not args.apply:
        print("\nSimulation — rien n'a été écrit. Relancer avec --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
