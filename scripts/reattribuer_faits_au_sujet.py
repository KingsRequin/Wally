#!/usr/bin/env python3
"""Déplace les faits rangés chez la mauvaise personne, d'après leur sujet.

Constaté en prod : onze faits « Cluth joue à Valorant », « Cluth utilise un
tracker de performance »… dans la mémoire de KingsRequin. Le LLM renvoyait
`target_user_id` = celui qui PARLE plutôt que celui dont on parle, et le code
prenait cet identifiant au mot.

Corrigé à la source (`FactExtractor._subject_owner`) ; ce script rattrape
l'existant. Même règle qu'en direct : correspondance EXACTE entre le premier mot
du souvenir et le pseudo d'un utilisateur connu — sans certitude on ne déplace
rien, une réattribution à tort mettrait un souvenir chez un inconnu.

`wally:self` est laissé tranquille : les pensées de Wally SUR quelqu'un
commencent par son nom mais lui appartiennent bien (c'est sa perspective).

Usage :
    python3 scripts/reattribuer_faits_au_sujet.py            # dry-run
    python3 scripts/reattribuer_faits_au_sujet.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

_MOT_INITIAL = re.compile(r"^([A-Za-zÀ-ÿ0-9_.\-]{2,32})\b")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Comptes liés : deux fiches d'une même personne. Sans ça, « jubeii1979 joue
    # à Darktide » quitterait la fiche Discord où vit toute sa mémoire pour sa
    # fiche Twitch vide — on couperait sa mémoire en deux au lieu de la corriger.
    canonique: dict[str, str] = {
        r["alias_id"]: r["canonical_id"]
        for r in db.execute(
            "SELECT alias_id, canonical_id FROM user_links WHERE status = 'accepted'"
        )
    }

    def _resoudre(uid: str) -> str:
        return canonique.get(uid, uid)

    # pseudo (normalisé) → compte canonique, en écartant les fiches sans nom
    par_nom: dict[str, str] = {}
    for r in db.execute("SELECT user_id, username FROM memory_users"):
        nom = (r["username"] or "").strip().casefold()
        if nom and not r["user_id"].startswith("unknown:"):
            par_nom.setdefault(nom, _resoudre(r["user_id"]))

    a_deplacer: list[tuple[int, str, str, str]] = []
    for r in db.execute(
        "SELECT id, user_id, content FROM atomic_facts WHERE status = 'active'"
    ):
        if r["user_id"].startswith("wally:"):
            continue  # sa perspective sur les autres — lui appartient
        m = _MOT_INITIAL.match((r["content"] or "").strip())
        if not m:
            continue
        proprietaire = par_nom.get(m.group(1).casefold())
        if proprietaire and proprietaire != _resoudre(r["user_id"]):
            a_deplacer.append((r["id"], r["user_id"], proprietaire, r["content"]))

    print(f"{len(a_deplacer)} fait(s) à réattribuer")
    for _id, avant, apres, contenu in a_deplacer:
        print(f"   {avant}  →  {apres}")
        print(f"      {contenu[:74]}")

    if not a_deplacer:
        db.close()
        return 0
    if not args.apply:
        print("\nRelancer avec --apply pour déplacer.")
        db.close()
        return 0

    db.executemany(
        "UPDATE atomic_facts SET user_id = ? WHERE id = ?",
        [(apres, _id) for _id, _av, apres, _c in a_deplacer],
    )
    db.commit()
    db.close()
    print(f"\n{len(a_deplacer)} fait(s) déplacé(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
