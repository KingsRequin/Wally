#!/usr/bin/env python3
"""Efface intégralement le profil mémoire d'une personne.

Retire tout ce qui constitue la connaissance que Wally a de quelqu'un : ses
faits (actifs, archivés, révolus), son portrait, son entrée mémoire, ses
liaisons de comptes, ses scores de confiance et d'affection.

Ne touche PAS aux journaux de conversation (`daily_log`, JSONL) : ce sont des
traces d'échanges collectifs, pas un profil. Le script les compte et le dit.

Usage :
    python3 scripts/effacer_profil_memoire.py discord:695688666236059688
    python3 scripts/effacer_profil_memoire.py discord:695688666236059688 --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3

# (table, colonne) balayées pour la forme préfixée ET la forme brute.
_CIBLES = [
    ("atomic_facts", "user_id"),
    ("user_profiles", "user_id"),
    ("memory_users", "user_id"),
    ("user_links", "canonical_id"),
    ("user_links", "alias_id"),
    ("trust_scores", "user_id"),
    ("love_scores", "user_id"),
    ("emotional_memory", "user_id"),
    ("memory_questions", "user_id"),
    ("user_aliases", "canonical_uid"),
]


def _existe(db: sqlite3.Connection, table: str, col: str) -> bool:
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return False
    return col in [r[1] for r in db.execute(f"PRAGMA table_info({table})")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("user_id", help="identifiant préfixé, ex. discord:123456")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    prefixe = args.user_id
    brut = prefixe.split(":", 1)[1] if ":" in prefixe else prefixe

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    print(f"Profil visé : {prefixe} (forme brute : {brut})\n")
    total = 0
    for table, col in _CIBLES:
        if not _existe(db, table, col):
            continue
        n = db.execute(
            f"SELECT count(*) FROM {table} WHERE {col} IN (?,?)", (prefixe, brut)
        ).fetchone()[0]
        if n:
            print(f"  {table}.{col:<16} {n}")
            total += n
    print(f"\nTotal à supprimer : {total} ligne(s)")

    # Signalé, jamais supprimé : ce sont des conversations, pas un profil.
    if _existe(db, "daily_log", "author"):
        n = db.execute(
            "SELECT count(*) FROM daily_log WHERE author LIKE ?", (f"%{brut}%",)
        ).fetchone()[0]
        if n:
            print(f"\n({n} ligne(s) de daily_log mentionnent cet identifiant — non touchées)")

    if not args.apply:
        print("\n(dry-run — relancer avec --apply)")
        return 0

    cur = db.cursor()
    for table, col in _CIBLES:
        if not _existe(db, table, col):
            continue
        cur.execute(f"DELETE FROM {table} WHERE {col} IN (?,?)", (prefixe, brut))
        if cur.rowcount:
            print(f"  supprimé {cur.rowcount:>4} de {table}.{col}")
    db.commit()
    print("\nProfil effacé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
