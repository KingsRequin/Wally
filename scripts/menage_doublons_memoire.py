#!/usr/bin/env python3
"""Rattrapage : rejoue la passe de ménage sur TOUS les utilisateurs d'un coup.

Le tri des doublons tourne normalement une personne par nuit (cron
`memory_cleanup`, cf. `DailyJournal.run_memory_cleanup`). Ce script existe pour
le backlog : la passe a été un no-op du 2026-06-20 (`77ffb94`) au rebranchement,
et sept semaines de paraphrases se sont accumulées. À 48 utilisateurs, attendre
le tour de chacun prendrait 48 nuits.

Il n'implémente AUCUNE logique de tri : il appelle `sort_user_memory()`, la même
méthode que le cron. Un seul endroit à corriger si le tri doit changer.

Archivage = `status='archived'` — réversible, rien n'est supprimé.

Usage :
    python3 scripts/menage_doublons_memoire.py              # dry-run (liste)
    python3 scripts/menage_doublons_memoire.py --apply      # applique
    python3 scripts/menage_doublons_memoire.py --apply --user discord:610550333042589752
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402

# Hors Docker les clés API ne sont pas dans l'environnement (cf. bot/main.py).
load_dotenv()


from bot.config import Config  # noqa: E402
from bot.db.database import Database  # noqa: E402
from bot.intelligence.journal import (  # noqa: E402
    _CLEANUP_EXCLUDED_USERS,
    _CLEANUP_MIN_FACTS,
    DailyJournal,
)
from bot.intelligence.memory.facts import FactStatus  # noqa: E402
from bot.intelligence.memory.service import MemoryService  # noqa: E402


async def _run(db_path: str, apply: bool, only_user: str | None) -> int:
    config = Config.load()
    db = await Database.create(db_path)
    memory = MemoryService(config)
    memory.set_embedding_backend(db_path=db_path)
    memory.set_db(db)

    store = memory.fact_store
    if store is None:
        logger.error("fact_store indisponible — backend V2 non initialisé")
        await db.close()
        return 1

    counts = await store.count_all_by_user()
    if only_user:
        targets = [only_user] if only_user in counts else []
        if not targets:
            logger.error("{u} n'a aucun fait actif", u=only_user)
    else:
        targets = sorted(
            (u for u, n in counts.items()
             if n >= _CLEANUP_MIN_FACTS and u not in _CLEANUP_EXCLUDED_USERS),
            key=lambda u: -counts[u],
        )

    if not apply:
        print(f"DRY-RUN — {len(targets)} utilisateur(s) seraient triés :")
        for uid in targets:
            print(f"  {counts[uid]:>5} faits actifs   {uid}")
        print("\nRelancer avec --apply pour appliquer.")
        await db.close()
        return 0

    from bot.core.llm.factory import create_llm_client

    secondary = create_llm_client(config.llm.secondary, db)
    # emotion=None : `sort_user_memory` ne touche pas au moteur émotionnel.
    journal = DailyJournal(config, secondary, secondary, None, memory, db=db)

    total_avant = total_apres = 0
    for i, uid in enumerate(targets, 1):
        avant = len(await store.get_by_user(uid, status=FactStatus.ACTIVE))
        logger.info("[{i}/{n}] {u} — {a} faits actifs", i=i, n=len(targets), u=uid, a=avant)
        try:
            await journal.sort_user_memory(uid)
        except Exception as exc:  # noqa: BLE001 — un utilisateur ne doit pas tout arrêter
            logger.warning("{u} : tri échoué, on passe au suivant : {e}", u=uid, e=exc)
            continue
        apres = len(await store.get_by_user(uid, status=FactStatus.ACTIVE))
        total_avant += avant
        total_apres += apres
        logger.info("[{i}/{n}] {u} — {a} → {b} faits", i=i, n=len(targets), u=uid, a=avant, b=apres)

    retires = total_avant - total_apres
    logger.info(
        "Terminé : {n} utilisateur(s), {a} → {b} faits actifs ({d} archivés)",
        n=len(targets), a=total_avant, b=total_apres, d=retires,
    )
    await db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    parser.add_argument("--user", default=None, help="un seul utilisateur (ex. discord:610…)")
    args = parser.parse_args()
    return asyncio.run(_run(args.db, args.apply, args.user))


if __name__ == "__main__":
    sys.exit(main())
