#!/usr/bin/env python3
"""Régénère TOUS les portraits de `user_profiles` avec les prompts actuels.

`UserModeler.refresh_profiles()` ne repasse chaque nuit que sur les personnes
dont un fait a bougé dans la journée. Après un changement de prompt, les
portraits des personnes silencieuses gardent donc leur ancienne rédaction —
indéfiniment pour qui ne parle plus.

Écrit le 2026-08-24 pour purger les genres INVENTÉS : aucun fait n'établissait
le genre de presque personne, le modèle le déduisait du pseudo, et 58 des 126
portraits parlaient au féminin. `user_portrait.md` interdit désormais de le
deviner ; il fallait encore repasser sur le stock.

Le `since` à l'époque zéro sélectionne toute personne ayant un fait actif : le
script n'a besoin d'aucun code neuf dans `UserModeler`.

Usage :
    PYTHONPATH=. python3 scripts/regenerer_portraits.py            # dry-run
    PYTHONPATH=. python3 scripts/regenerer_portraits.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger  # noqa: E402

from bot.config import Config  # noqa: E402
from bot.core.llm.factory import create_llm_client  # noqa: E402
from bot.db.database import Database  # noqa: E402
from bot.intelligence.memory.user_modeler import UserModeler  # noqa: E402

_EPOQUE_ZERO = "1970-01-01T00:00:00"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = await Database.create(args.db)
    try:
        cibles = await db.get_users_with_recent_facts(_EPOQUE_ZERO)
        print(f"{len(cibles)} personne(s) à repasser.")
        if not args.apply:
            print("dry-run — relancer avec --apply")
            return 0

        config = Config.load()
        llm = create_llm_client(config.llm.secondary, db)
        modeler = UserModeler(db, llm)
        logger.info("Régénération de {n} portrait(s)...", n=len(cibles))
        await modeler.refresh_profiles(since=_EPOQUE_ZERO)
    finally:
        # Sans ça, le thread d'aiosqlite parle à une boucle déjà fermée et
        # crache une traceback après le dernier print.
        await db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
