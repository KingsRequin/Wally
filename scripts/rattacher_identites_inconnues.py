#!/usr/bin/env python3
"""Solde les identités provisoires `unknown:<pseudo>` restées en base.

`fact_extractor` range sous `unknown:<pseudo>` ce qu'il apprend d'un tiers
qu'il ne sait pas encore rattacher à un compte. C'est une clé PROVISOIRE :
`_reconcile_orphan_facts` déplace ses faits vers l'uid canonique dès que
l'alias est résolu.

Deux fuites laissaient des restes, corrigées dans le code le 2026-08-26 :

  · le PORTRAIT ne suivait pas les faits. Bâti sur eux, il ne décrivait plus
    rien dès qu'ils changeaient de clé — et `get_user_profile()` n'étant
    appelé qu'avec l'uid canonique, il n'était lu par personne. Régénéré
    chaque nuit quand même, à un appel LLM pièce ;
  · `UserModeler` ne filtrait que `wally:`, pas `unknown:`.

Ce script rattrape l'existant, en deux gestes distincts :

  · **pseudo connu de `user_aliases`** → les faits sont DÉPLACÉS vers l'uid
    canonique (même geste que `reassign_user`), le portrait provisoire est
    effacé ;
  · **pseudo inconnu** → les faits RESTENT sous `unknown:` (c'est leur raison
    d'être, ils attendent une résolution), seul le portrait part.

    python3 scripts/rattacher_identites_inconnues.py            # aperçu
    python3 scripts/rattacher_identites_inconnues.py --appliquer
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path(__file__).resolve().parent.parent / "data" / "wally.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit vraiment (sans ce drapeau : simple aperçu)")
    ap.add_argument("--base", default=str(BASE))
    args = ap.parse_args()

    c = sqlite3.connect(args.base)

    # Toutes les clés provisoires, qu'elles portent des faits, un portrait, ou
    # les deux : un portrait seul est justement le cas qu'on ne voyait pas.
    inconnus = sorted({
        u for (u,) in c.execute(
            "SELECT DISTINCT user_id FROM atomic_facts WHERE user_id LIKE 'unknown:%' "
            "UNION SELECT user_id FROM user_profiles WHERE user_id LIKE 'unknown:%'")
    })

    print(f"IDENTITÉS PROVISOIRES : {len(inconnus)}")
    plan = []
    for uid in inconnus:
        pseudo = uid.split(":", 1)[1]
        ligne = c.execute(
            "SELECT canonical_uid FROM user_aliases WHERE LOWER(nickname) = ?",
            (pseudo.lower(),)).fetchone()
        canonique = ligne[0] if ligne else None
        faits = c.execute(
            "SELECT COUNT(*) FROM atomic_facts WHERE user_id = ?", (uid,)).fetchone()[0]
        portrait = c.execute(
            "SELECT COUNT(*) FROM user_profiles WHERE user_id = ?", (uid,)).fetchone()[0]
        plan.append((uid, canonique, faits, portrait))
        geste = f"faits → {canonique}" if canonique else "faits gardés (pseudo non résolu)"
        print(f"  {uid:22} {faits} fait(s), {portrait} portrait  ·  {geste}")

    if not args.appliquer:
        print("\n(aperçu seul — relancer avec --appliquer pour écrire)")
        return 0

    deplaces = portraits = 0
    for uid, canonique, _faits, _portrait in plan:
        if canonique:
            cur = c.execute(
                "UPDATE atomic_facts SET user_id = ? WHERE user_id = ?", (canonique, uid))
            deplaces += cur.rowcount
        cur = c.execute("DELETE FROM user_profiles WHERE user_id = ?", (uid,))
        portraits += cur.rowcount
    c.commit()
    print(f"\n✅ {deplaces} fait(s) rattaché(s), {portraits} portrait(s) provisoire(s) effacé(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
