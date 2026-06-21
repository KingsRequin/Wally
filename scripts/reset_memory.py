#!/usr/bin/env python3
"""Reset propre de la mémoire V2 (faits) — repart à zéro sur le backend FTS5.

Vide `atomic_facts` + `fact_relations` (les triggers nettoient la table FTS5).
À lancer après le port mémoire jarvis-OS pour effacer l'ancienne mémoire
incohérente (256 faits, clés éclatées brut/préfixé, embeddings Qdrant orphelins).

Usage :
    python3 scripts/reset_memory.py            # DB par défaut (DB_PATH ou data/wally.db)
    python3 scripts/reset_memory.py --yes      # sans confirmation
    DB_PATH=/chemin/wally.db python3 scripts/reset_memory.py --yes

Les anciennes collections Qdrant (wally_v2_facts, wally_memory) ne sont plus
utilisées — Qdrant a été retiré. data/qdrant/ peut être supprimé manuellement.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import aiosqlite


async def reset(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        before = (await (await db.execute("SELECT COUNT(*) FROM atomic_facts")).fetchone())[0]
        await db.execute("DELETE FROM fact_relations")
        await db.execute("DELETE FROM atomic_facts")
        await db.commit()
        # Sanity : la table FTS5 doit être vide (maintenue par triggers).
        try:
            fts = (await (await db.execute("SELECT COUNT(*) FROM atomic_facts_fts")).fetchone())[0]
        except Exception:
            fts = "n/a"
    print(f"Mémoire réinitialisée : {before} faits supprimés (atomic_facts_fts restant: {fts}).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset de la mémoire V2 (faits).")
    parser.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"), help="chemin de la DB SQLite")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"DB introuvable : {args.db}", file=sys.stderr)
        return 1

    if not args.yes:
        rep = input(f"Vider TOUTE la mémoire de faits de {args.db} ? [oui/non] ").strip().lower()
        if rep not in ("oui", "o", "yes", "y"):
            print("Annulé.")
            return 0

    asyncio.run(reset(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
