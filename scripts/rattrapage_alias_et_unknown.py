#!/usr/bin/env python3
"""Répare les identifiants d'alias et les clés `unknown:` en base.

Deux défauts corrigés à la source le 2026-08-10, dont il reste des traces :

1. `resolved_user_id` rendu par le LLM était écrit tel quel dans `user_aliases`.
   129 lignes sur 188 n'ont donc pas de namespace (« 610550333042589752 » au
   lieu de « discord:610… »). `canonical_uid.split(":", 1)` ne rend qu'une
   partie : la branche qui injecte les souvenirs d'un tiers est sautée pour
   69 % des pseudos connus, et l'uid désigne un espace que personne ne lit.
   On rattache chaque identifiant nu au compte connu qui porte ce raw_id ; sans
   correspondance certaine, on ne touche à rien.

2. Les faits d'un inconnu étaient écrits sous `unknown:<Pseudo>` en casse
   d'origine, alors que tout le reste de la chaîne minuscule la clé. Les
   orphelins n'étaient donc jamais migrés vers le compte reconnu plus tard.

Usage :
    python3 scripts/rattrapage_alias_et_unknown.py            # dry-run
    python3 scripts/rattrapage_alias_et_unknown.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Index raw_id → uid préfixé, construit sur les comptes réellement connus.
    connus: dict[str, list[str]] = {}
    for r in db.execute("SELECT user_id FROM memory_users WHERE instr(user_id, ':') > 0"):
        uid = r["user_id"]
        connus.setdefault(uid.split(":", 1)[1], []).append(uid)

    nus = db.execute(
        "SELECT nickname, canonical_uid FROM user_aliases WHERE instr(canonical_uid, ':') = 0"
    ).fetchall()

    reparables: list[tuple[str, str, str]] = []
    ambigus: list[str] = []
    orphelins: list[str] = []
    for r in nus:
        candidats = connus.get(r["canonical_uid"], [])
        # `unknown:` n'est pas une plateforme, c'est un fourre-tout : quand un
        # vrai namespace existe pour le même raw_id, il l'emporte sans ambiguïté.
        reels = [c for c in candidats if not c.startswith("unknown:")]
        if reels:
            candidats = reels
        if len(candidats) == 1:
            reparables.append((r["nickname"], r["canonical_uid"], candidats[0]))
        elif len(candidats) > 1:
            ambigus.append(f"{r['nickname']} → {r['canonical_uid']} ({candidats})")
        else:
            orphelins.append(f"{r['nickname']} → {r['canonical_uid']}")

    print(f"Alias sans namespace : {len(nus)}")
    print(f"  réparables (un seul compte porte ce raw_id) : {len(reparables)}")
    print(f"  ambigus (plusieurs comptes)                 : {len(ambigus)}")
    print(f"  sans compte correspondant                   : {len(orphelins)}")
    for a in ambigus[:5]:
        print(f"    ambigu  : {a}")
    for o in orphelins[:5]:
        print(f"    orphelin: {o}")

    maj_users = db.execute(
        "SELECT count(*) FROM memory_users "
        "WHERE user_id LIKE 'unknown:%' AND user_id != lower(user_id)"
    ).fetchone()[0]
    maj_facts = db.execute(
        "SELECT count(*) FROM atomic_facts "
        "WHERE user_id LIKE 'unknown:%' AND user_id != lower(user_id)"
    ).fetchone()[0]
    print(f"\nClés `unknown:` en casse d'origine : {maj_users} dans memory_users, "
          f"{maj_facts} dans atomic_facts")

    if not args.apply:
        print("\n(dry-run — relancer avec --apply)")
        return 0

    cur = db.cursor()
    for nickname, nu, prefixe in reparables:
        # `OR IGNORE` : le nickname peut déjà exister sous la forme préfixée.
        cur.execute(
            "UPDATE OR IGNORE user_aliases SET canonical_uid = ? "
            "WHERE nickname = ? AND canonical_uid = ?",
            (prefixe, nickname, nu),
        )
    print(f"\nAlias repréfixés : {len(reparables)}")

    # Minuscules : on fusionne au lieu d'échouer si la forme minuscule existe déjà.
    cur.execute(
        "UPDATE OR REPLACE memory_users SET user_id = lower(user_id) "
        "WHERE user_id LIKE 'unknown:%' AND user_id != lower(user_id)"
    )
    print(f"memory_users normalisés : {cur.rowcount}")
    cur.execute(
        "UPDATE atomic_facts SET user_id = lower(user_id) "
        "WHERE user_id LIKE 'unknown:%' AND user_id != lower(user_id)"
    )
    print(f"atomic_facts normalisés : {cur.rowcount}")
    db.commit()

    restant = db.execute(
        "SELECT count(*) FROM user_aliases WHERE instr(canonical_uid, ':') = 0"
    ).fetchone()[0]
    print(f"\nReste sans namespace (ambigus + orphelins) : {restant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
