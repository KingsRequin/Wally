#!/usr/bin/env python3
"""Ramène les dates des faits à un seul format : UTC naïf.

Deux formats coexistaient dans les mêmes colonnes : `MemoryService.add()`
écrivait en aware (`datetime.now(timezone.utc)` → suffixe `+00:00`), tout le
reste du projet en naïf (`datetime.utcnow()`, dans `AtomicFact` et la quinzaine
de requêtes de `facts.py`). Toute soustraction directe entre les deux lève
`TypeError` — d'où les helpers défensifs qui recollent `tzinfo` après coup.

La source est corrigée ; ce script rattrape l'existant. Le suffixe `+00:00`
désigne bien UTC : le retirer ne déplace aucune date, il aligne l'écriture.

Usage :
    python3 scripts/normaliser_dates_faits.py            # dry-run
    python3 scripts/normaliser_dates_faits.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3

_COLONNES = ("created_at", "last_seen_at", "expires_at", "scheduled_at")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    colonnes = [r[1] for r in db.execute("PRAGMA table_info(atomic_facts)")]

    total = 0
    for col in _COLONNES:
        if col not in colonnes:
            continue
        n = db.execute(
            f"SELECT count(*) FROM atomic_facts WHERE {col} LIKE '%+00:00'"
        ).fetchone()[0]
        print(f"  {col:<14} {n} ligne(s) en format aware")
        total += n
    print(f"\nTotal à normaliser : {total}")

    if not args.apply:
        print("\n(dry-run — relancer avec --apply)")
        return 0

    cur = db.cursor()
    for col in _COLONNES:
        if col not in colonnes:
            continue
        cur.execute(
            f"UPDATE atomic_facts SET {col} = replace({col}, '+00:00', '') "
            f"WHERE {col} LIKE '%+00:00'"
        )
        if cur.rowcount:
            print(f"  {col}: {cur.rowcount} normalisée(s)")
    db.commit()

    restant = sum(
        db.execute(f"SELECT count(*) FROM atomic_facts WHERE {c} LIKE '%+00:00'").fetchone()[0]
        for c in _COLONNES if c in colonnes
    )
    print(f"\nReste en aware : {restant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
