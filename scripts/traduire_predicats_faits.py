#!/usr/bin/env python3
"""Réécrit en français le texte des faits rendus depuis leur triplet S-P-O.

Le vocabulaire des prédicats est anglais (`is`, `has`, `plays`…) — volontaire,
c'est la clé de déduplication. Mais le texte lisible était construit en collant
`subject + predicate + object` tel quel, et cette phrase part au prompt que
Wally lit sur les gens :

    polylrose has piscine
    mks_zedd plays Apex Legends
    polylrose knows mécaniques de fragments héritages

Corrigé à la source (`vocab.render_triplet`) ; ce script rattrape l'existant.

Prudence : on ne réécrit QUE les faits dont le `content` est exactement l'ancien
rendu brut. Un texte reformulé à la main ou par le ménage nocturne n'est jamais
écrasé. La colonne `predicate` n'est pas touchée — la réconciliation compare
dessus.

Usage :
    python3 scripts/traduire_predicats_faits.py            # dry-run
    python3 scripts/traduire_predicats_faits.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.intelligence.memory.vocab import _PREDICATE_FR, render_triplet  # noqa: E402


def _formes_generees(subject: str, predicate: str, object_: str) -> set[str]:
    """Les textes que le code a pu produire lui-même pour ce triplet.

    Deux formes ont existé : les trois morceaux collés avec le prédicat anglais
    (« mks_zedd plays Apex Legends »), puis le prédicat traduit sans garde sur
    les objets déjà conjugués (« kingsrequin est va bien »). Un texte qui ne
    correspond à aucune des deux a été rédigé ou reformulé — on n'y touche pas.
    """
    s, p, o = ((x or "").strip() for x in (subject, predicate, object_))
    brut = " ".join(x for x in (s, p, o) if x).strip()
    traduit = " ".join(x for x in (s, _PREDICATE_FR.get(p, p), o) if x).strip()
    return {brut, traduit}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, content, subject, predicate, object FROM atomic_facts "
        "WHERE predicate IS NOT NULL AND predicate != ''"
    ).fetchall()

    a_changer: list[tuple[int, str, str]] = []
    intacts = 0
    for r in rows:
        actuel = (r["content"] or "").strip()
        if actuel not in _formes_generees(r["subject"], r["predicate"], r["object"]):
            intacts += 1  # texte rédigé ou reformulé — on n'y touche pas
            continue
        nouveau = render_triplet(r["subject"], r["predicate"], r["object"])
        if nouveau and nouveau != actuel:
            a_changer.append((r["id"], actuel, nouveau))

    print(f"{len(rows)} faits porteurs d'un triplet")
    print(f"  {intacts} au texte personnalisé — laissés tels quels")
    print(f"  {len(a_changer)} à réécrire")
    for _id, ancien, nouveau in a_changer[:12]:
        print(f"     {ancien[:58]}")
        print(f"  →  {nouveau[:58]}")
    if len(a_changer) > 12:
        print(f"     … et {len(a_changer) - 12} autres")

    if not args.apply:
        print("\nRelancer avec --apply pour écrire.")
        db.close()
        return 0

    db.executemany(
        "UPDATE atomic_facts SET content = ? WHERE id = ?",
        [(nouveau, _id) for _id, _a, nouveau in a_changer],
    )
    db.commit()
    db.close()
    print(f"\n{len(a_changer)} faits réécrits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
