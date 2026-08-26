#!/usr/bin/env python3
"""Découpe les faits que le chemin Twitch avait rangés COLLÉS.

Jusqu'au 2026-08-26, `_post_process` côté Twitch faisait
`memory.add(..., "\\n".join(user_facts))` : N faits extraits d'un message
finissaient dans UNE ligne de `atomic_facts`. Discord, lui, bouclait — d'où
147 blocs d'un côté et zéro de l'autre.

Ce qu'un bloc collé coûte, et qui ne se voit nulle part :

  · aucun des faits ne peut être écrasé individuellement. Une correction de
    l'intéressé ne remplace rien, elle s'ajoute à côté — et c'est le défaut de
    fond derrière « un tic qui résiste aux consignes » ;
  · la recherche FTS remonte le bloc entier, donc N−1 faits hors sujet qui
    mangent le budget de contexte ;
  · la dédup compare des blocs : deux blocs partageant trois faits sur quatre
    passent pour deux faits distincts.

Le code est corrigé ; ce script rattrape l'existant. Chaque ligne du bloc
devient un fait à part, qui hérite de tout le reste (personne, catégorie,
origine, dates, importance). Le bloc d'origine est ARCHIVÉ, jamais supprimé —
convention du projet, et seule façon de revenir en arrière.

  · Les lignes vides et les puces (« - », « • ») sont nettoyées : le modèle en
    produit, et « - aime Apex » n'est pas le même texte que « aime Apex ».
  · Un fait déjà présent à l'identique pour la même personne n'est pas
    réinséré — le découpage ne doit pas créer de doublon avec ce que la
    réconciliation a déjà rangé.
  · Les faits `wally:self` sont ÉPARGNÉS : ses pensées sont de la prose, leurs
    retours à la ligne sont des paragraphes, pas des séparateurs.

    python3 scripts/decoller_faits.py            # montre, ne touche à rien
    python3 scripts/decoller_faits.py --appliquer
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path(__file__).resolve().parent.parent / "data" / "wally.db"

# La puce que le modèle ajoute parfois en tête de ligne.
_PUCE = re.compile(r"^\s*[-•*—]\s*")


def lignes_du_bloc(contenu: str) -> list[str]:
    """Les faits d'un bloc, nettoyés. Liste vide si ce n'est pas un bloc."""
    lignes = [_PUCE.sub("", l).strip() for l in (contenu or "").split("\n")]
    return [l for l in lignes if l]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit vraiment (sans ce drapeau : simple aperçu)")
    ap.add_argument("--base", default=str(BASE))
    args = ap.parse_args()

    c = sqlite3.connect(args.base)

    # Les colonnes lues une fois, à la source : elles servent à la fois à
    # nommer les champs ici et à recopier le fait à l'identique plus bas. Un
    # `row_factory` ferait la première moitié du travail et laisserait la
    # seconde à une seconde requête.
    curseur = c.execute(
        "SELECT * FROM atomic_facts WHERE status = 'active' "
        "AND instr(content, char(10)) > 0 AND user_id != 'wally:self'")
    colonnes = [d[0] for d in curseur.description]
    blocs = [
        r for r in (dict(zip(colonnes, ligne)) for ligne in curseur)
        if len(lignes_du_bloc(r["content"])) > 1
    ]
    total = sum(len(lignes_du_bloc(r["content"])) for r in blocs)
    print(f"BLOCS à découper : {len(blocs)}  →  {total} faits")
    for r in blocs[:6]:
        print(f"  [{r['user_id'][:22]:22}] {r['origin'] or '(sans origine)'}")
        for ligne in lignes_du_bloc(r["content"]):
            print(f"        · {ligne[:88]}")
    if len(blocs) > 6:
        print(f"  … et {len(blocs) - 6} bloc(s) de plus")

    if not args.appliquer:
        print("\n(aperçu seul — relancer avec --appliquer pour écrire)")
        return 0

    # Le fait découpé est le MÊME fait : il ne doit ni rajeunir ni changer de
    # personne. `id` est exclu (auto-incrément), `content` est remplacé ligne
    # par ligne, tout le reste est recopié tel quel.
    portees = [n for n in colonnes if n not in ("id", "content")]

    inseres = archives = doublons = 0
    for r in blocs:
        for ligne in lignes_du_bloc(r["content"]):
            # La MÊME clé que l'index unique de la table
            # (`user_id`, `category`, `LOWER(TRIM(content))`) : comparer le
            # texte brut laissait passer « Aime les memes » face à « aime les
            # memes », et l'INSERT tombait sur une IntegrityError au 12ᵉ bloc.
            deja = c.execute(
                "SELECT 1 FROM atomic_facts WHERE user_id = ? AND category IS ? "
                "AND LOWER(TRIM(content)) = LOWER(TRIM(?)) AND status = 'active' "
                "LIMIT 1", (r["user_id"], r["category"], ligne)).fetchone()
            if deja:
                doublons += 1
                continue
            valeurs = [r[n] for n in portees]
            c.execute(
                f"INSERT INTO atomic_facts (content, {', '.join(portees)}) "  # noqa: S608 — noms de colonnes lus du schéma
                f"VALUES ({', '.join(['?'] * (len(portees) + 1))})",
                [ligne, *valeurs])
            inseres += 1
        c.execute("UPDATE atomic_facts SET status = 'archived' WHERE id = ?", (r["id"],))
        archives += 1
    c.commit()
    print(f"\n✅ {archives} bloc(s) archivé(s), {inseres} fait(s) créé(s), "
          f"{doublons} déjà présent(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
