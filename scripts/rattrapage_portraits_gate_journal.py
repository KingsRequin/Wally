#!/usr/bin/env python3
"""Nettoie les traces laissées par trois défauts corrigés le 2026-08-10.

1. Portraits attribués à Wally — `UserModeler` ne passait jamais le nom de la
   personne au LLM. Le seul nom du contexte étant celui du bot, le modèle
   écrivait « Wally, c'est un électricien en industrie dans le Nord… ».
   Ces fiches sont injectées au prompt à chaque message de la personne.
   On les supprime : elles seront régénérées la nuit suivante, avec le nom.

2. Profils rangés sous un identifiant NU (sans `platform:`) — fabriqués par le
   ResponseGate, qui écrivait ses traces sous l'id brut. La lecture se fait
   toujours sous la forme préfixée : ces fiches ne sont lues par personne, et
   chaque nuit le modeler dépensait un appel LLM pour les régénérer.

3. Faits `source='gate'` sous identifiant nu — mêmes orphelins, tous déjà
   archivés et périmés. On les supprime plutôt que de les repréfixer : une
   trace « j'ai ignoré ce message » a 24 h de durée de vie utile.

4. Entrées de journal qui ne sont que le message d'excuse du LLM —
   `complete()` ne lève pas, il retourne FALLBACK_RESPONSE, et rien ne le
   testait. Ces entrées étaient publiées, archivées, puis relues le lendemain
   comme « ton journal d'hier » et versées à la synthèse narrative.

Usage :
    python3 scripts/rattrapage_portraits_gate_journal.py            # dry-run
    python3 scripts/rattrapage_portraits_gate_journal.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.core.llm.base import FALLBACK_RESPONSE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # 1 — portraits qui parlent du bot au lieu de la personne
    portraits = db.execute(
        "SELECT user_id, substr(portrait,1,70) AS debut FROM user_profiles "
        "WHERE lower(trim(portrait)) LIKE 'wally%'"
    ).fetchall()

    # 2 — profils sous identifiant nu (jamais relus)
    orphelins = db.execute(
        "SELECT user_id FROM user_profiles WHERE instr(user_id, ':') = 0"
    ).fetchall()

    # 3 — faits du gate sous identifiant nu
    faits = db.execute(
        "SELECT count(*) AS n FROM atomic_facts "
        "WHERE source = 'gate' AND instr(user_id, ':') = 0"
    ).fetchone()["n"]

    # 4 — journées remplacées par le message d'excuse
    journees = db.execute(
        "SELECT date, word_count FROM journal_archive WHERE trim(content) = ? ORDER BY date",
        (FALLBACK_RESPONSE,),
    ).fetchall()

    print(f"Portraits attribués à Wally : {len(portraits)}")
    for r in portraits:
        print(f"   {r['user_id']:<32} {r['debut']}")
    print(f"\nProfils sous identifiant nu : {len(orphelins)}")
    for r in orphelins:
        print(f"   {r['user_id']}")
    print(f"\nFaits 'gate' sous identifiant nu : {faits}")
    print(f"\nJournées réduites au message d'excuse : {len(journees)}")
    for r in journees:
        print(f"   {r['date']} ({r['word_count']} mots)")

    if not args.apply:
        print("\n(dry-run — relancer avec --apply)")
        return 0

    cur = db.cursor()
    cur.execute("DELETE FROM user_profiles WHERE lower(trim(portrait)) LIKE 'wally%'")
    n_portraits = cur.rowcount
    cur.execute("DELETE FROM user_profiles WHERE instr(user_id, ':') = 0")
    n_orphelins = cur.rowcount
    cur.execute("DELETE FROM atomic_facts WHERE source = 'gate' AND instr(user_id, ':') = 0")
    n_faits = cur.rowcount
    cur.execute("DELETE FROM journal_archive WHERE trim(content) = ?", (FALLBACK_RESPONSE,))
    n_journees = cur.rowcount
    db.commit()

    print(
        f"\nSupprimés — portraits: {n_portraits} | profils orphelins: {n_orphelins} | "
        f"faits gate: {n_faits} | journées: {n_journees}"
    )
    print("Les portraits légitimes seront régénérés à la passe nocturne du UserModeler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
