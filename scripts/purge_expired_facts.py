#!/usr/bin/env python3
"""Purge rétroactive des faits éphémères déjà périmés.

Les faits créés AVANT l'introduction du champ `expires_at` n'ont pas de date de
péremption. Ce script les détecte a posteriori via les marqueurs temporels de
leur contenu (« ce soir », « demain », « ce matin »…), recalcule leur date de
péremption à partir de leur `created_at`, et archive ceux déjà périmés.

Archivage = `status='archived'` (réversible : les données restent en base, mais
ne sont plus rappelées ni affichées). Aucune suppression.

Usage :
    python3 scripts/purge_expired_facts.py            # dry-run (liste seulement)
    python3 scripts/purge_expired_facts.py --apply     # applique l'archivage
    DB_PATH=/chemin/wally.db python3 scripts/purge_expired_facts.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

# Réutilise EXACTEMENT la même heuristique que l'extraction live.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.intelligence.fact_extractor import _compute_expiry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge rétroactive des faits éphémères périmés")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"),
                        help="chemin de la DB SQLite")
    parser.add_argument("--apply", action="store_true",
                        help="applique l'archivage (sinon dry-run)")
    args = parser.parse_args()

    now = datetime.utcnow()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Faits actifs sans péremption déjà posée (les anciens). On se restreint aux
    # catégories de faits UTILISATEUR (FAIT/PREF/REL/LANG) : la péremption ne
    # concerne que les intentions/événements rapportés, jamais la cognition
    # interne (THOUGHT/DESIRE/GOAL/EMOTION), dont les monologues contiennent
    # souvent « ce matin/ce soir » sans être des faits éphémères.
    rows = db.execute(
        """SELECT id, content, created_at, origin, category FROM atomic_facts
           WHERE status = 'active' AND expires_at IS NULL
             AND category IN ('FAIT', 'PREF', 'REL', 'LANG')"""
    ).fetchall()

    to_archive: list[tuple[int, str, str]] = []
    for r in rows:
        try:
            created = datetime.fromisoformat(r["created_at"])
        except (ValueError, TypeError):
            continue
        if created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        # ttl=None → seule l'heuristique de marqueurs temporels décide.
        expiry = _compute_expiry(None, r["content"], created)
        if expiry is not None and expiry <= now:
            to_archive.append((r["id"], r["created_at"][:16], r["content"]))

    print(f"DB : {args.db}")
    print(f"Faits actifs sans expires_at : {len(rows)}")
    print(f"Faits éphémères PÉRIMÉS détectés : {len(to_archive)}\n")
    for fid, created, content in to_archive:
        one_line = " ".join(content.split())[:90]
        print(f"  #{fid} [{created}] {one_line}")

    if not to_archive:
        print("\nRien à archiver.")
        db.close()
        return 0

    if not args.apply:
        print(f"\n[DRY-RUN] {len(to_archive)} faits seraient archivés. "
              f"Relancer avec --apply pour appliquer.")
        db.close()
        return 0

    ids = [fid for fid, _, _ in to_archive]
    placeholders = ",".join("?" * len(ids))
    cur = db.execute(
        f"UPDATE atomic_facts SET status='archived' WHERE id IN ({placeholders})",
        ids,
    )
    db.commit()
    print(f"\n✅ {cur.rowcount} faits archivés (status='archived', réversible).")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
