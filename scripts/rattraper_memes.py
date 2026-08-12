#!/usr/bin/env python3
"""Rattrape la banque de memes : décrit les muets, convertit ce qui y gagne.

Les memes déposés à la main n'ont pas toujours de `.txt`. Leur description
retombe alors sur le nom du fichier — « meme80 » : `pick(hint)` cherchant dans
les descriptions, ils sont introuvables par mot-clé, et Wally les commente à
l'aveugle. Ceux déposés depuis la dernière conversion pèsent aussi dix fois leur
poids.

Ce script n'a pas de logique propre : il déroule `bot.core.meme_import` sur le
dossier. Ce que fait la commande Discord à l'unité, il le fait en série.

La simulation ne coûte RIEN et n'écrit RIEN : sans `--apply`, aucune image n'est
envoyée au modèle de vision (donc aucune facture) et la conversion se fait dans
un dossier temporaire. Écrire ses `.webp` d'essai dans `data/memes/` — un
dossier bind-monté que le rotateur relit à chaque tirage — laissait à la
moindre interruption des orphelins qu'`empreintes()` prenait pour des memes.

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
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from bot.config import Config  # noqa: E402
from bot.core import meme_import  # noqa: E402
from bot.core.memes import _EXTENSIONS, _MEDIA_TYPES, tronquer_description  # noqa: E402


async def _vision(db_path: str):
    """Le service de vision du bot, câblé comme au démarrage.

    Le repli est `_VISION_MODEL_DEFAUT`, IMPORTÉ de `bootstrap` et non recopié.
    Retomber sur `secondary_model` est précisément la panne que `bootstrap`
    interdit par écrit : le dashboard écrase ce champ dès qu'on change le modèle
    texte secondaire, et un secondaire DeepSeek envoyait la vision interroger
    OpenAI avec un modèle inexistant — 404 par image, filtrés par `analyze()`,
    donc « aucune description obtenue » en boucle et sortie 0.

    La clé est contrôlée comme dans `bootstrap` : sans elle `OpenAILLMClient`
    retombe sur `dummy-key-for-testing`, `available` reste vrai, et le script
    facturerait des 401 au lieu de nommer la cause.

    La vraie `Database` est branchée pour que `log_cost` enregistre : ce
    rattrapage facture comme n'importe quel appel, l'onglet des coûts n'a pas à
    ignorer une dépense parce qu'elle vient d'un script.
    """
    from bot.bootstrap import _VISION_MODEL_DEFAUT
    from bot.core.llm.openai_client import OpenAILLMClient
    from bot.core.vision import VisionService
    from bot.db.database import Database

    config = Config.load()
    modele = getattr(config.openai, "vision_model", "") or _VISION_MODEL_DEFAUT
    db = await Database.create(db_path)
    client = None
    if os.environ.get("OPENAI_API_KEY"):
        # Mêmes réglages que `bootstrap` : « low » et non le « medium » par
        # défaut, sinon le rattrapage paie plus de jetons de raisonnement par
        # meme que le bot lui-même.
        client = OpenAILLMClient(
            model=modele, db=db, temperature=0.3, max_tokens=400,
            reasoning_effort="low",
        )
    return VisionService(client), db, modele


async def _decrire(svc, chemin: Path) -> str:
    """Décrit un fichier LOCAL : il n'est pas en ligne, on l'envoie en base64."""
    mime = _MEDIA_TYPES.get(chemin.suffix.lower(), "image/png")
    url = f"data:{mime};base64," + base64.b64encode(chemin.read_bytes()).decode()
    texte = await svc.analyze(
        [url], purpose="meme_describe", prompt_name="meme_describe_system"
    )
    # Tronquée à l'écriture comme le fait `importer()` : `_describe` ne relira
    # pas au-delà, écrire plus long ne ferait qu'une phrase coupée en deux.
    return tronquer_description(texte or "")


def _convertir_dossier(dossier: Path, apply: bool) -> None:
    """La même garde que `convertir_memes_webp.py`, sur les fichiers restants.

    Seule la boucle de parcours est écrite ici : `convertir` et
    `verifier_conversion` viennent du module partagé, donc l'unique garde
    anti-perte d'animation reste unique.

    Le WebP est fabriqué dans un dossier temporaire VOISIN de la banque, jamais
    dedans : un essai refusé ne laisse rien derrière lui, et le voisinage garde
    la mise en place atomique (même système de fichiers).
    """
    gagne = perdu = 0
    with tempfile.TemporaryDirectory(dir=dossier.parent, prefix=".rattrapage-") as tmp:
        atelier = Path(tmp)
        for src in sorted(dossier.iterdir()):
            if not src.is_file() or src.suffix.lower() not in meme_import.A_CONVERTIR:
                continue
            final = src.with_suffix(".webp")
            if final.exists():
                print(f"  {src.name:16} laissé — {final.name} existe déjà")
                continue
            dst = atelier / final.name
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
                shutil.move(str(dst), str(final))
                txt = meme_import.sidecar_de(src)
                if txt is not None:
                    txt.rename(final.with_name(final.name + ".txt"))
                src.unlink()
            else:
                dst.unlink()
    if gagne:
        print(f"  → {gagne / 1e6:.1f} Mo deviennent {perdu / 1e6:.1f} Mo")


async def _decrire_les_muets(dossier: Path, apply: bool, db_path: str) -> None:
    muets = meme_import.memes_sans_description(dossier)
    print(f"{len(muets)} meme(s) sans description")
    a_decrire = []
    for chemin in muets:
        if chemin.suffix.lower() not in _EXTENSIONS:
            print(f"  {chemin.name:16} laissé — pas d'analyse possible sur une vidéo")
            continue
        a_decrire.append(chemin)

    if not a_decrire:
        return
    if not apply:
        # Appeler le modèle « pour voir » facturerait une simulation, et le
        # script conclut pourtant « rien n'a été écrit ».
        for chemin in a_decrire:
            print(f"  {chemin.name:16} serait décrit — non appelé en simulation")
        return

    svc, db, modele = await _vision(db_path)
    try:
        if not svc.available:
            print(f"  OPENAI_API_KEY absente — vision ({modele}) indisponible, "
                  f"aucune description écrite")
            return
        for chemin in a_decrire:
            texte = await _decrire(svc, chemin)
            if not texte:
                print(f"  {chemin.name:16} aucune description obtenue")
                continue
            print(f"  {chemin.name:16} {texte[:90]}")
            chemin.with_name(chemin.name + ".txt").write_text(texte, encoding="utf-8")
    finally:
        await db.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossier", default="data/memes")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true",
                        help="écrit ; sans lui, rien n'est modifié")
    parser.add_argument("--sans-decrire", action="store_true",
                        help="ne fait que la conversion")
    args = parser.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}")
        return 1

    if not args.sans_decrire:
        await _decrire_les_muets(dossier, args.apply, args.db)

    print("\nConversion en WebP :")
    _convertir_dossier(dossier, args.apply)

    if not args.apply:
        print("\nSimulation — rien n'a été écrit, rien n'a été facturé. "
              "Relancer avec --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
