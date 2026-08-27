#!/usr/bin/env python3
"""Quelle part du prompt est servie par le cache du provider — LECTURE SEULE.

Né du 2026-08-27, d'une question qui n'avait pas de réponse chiffrée : « peut-on
n'exposer un outil au LLM que si la phrase contient certains mots ? »

Les définitions d'outils pèsent ~8 400 des ~19 400 jetons d'un prompt Twitch et
se sérialisent EN TÊTE. Les faire varier d'un message à l'autre invaliderait donc
le cache de préfixe sur tout ce qui suit — pas seulement sur les outils retirés.
L'économie annoncée pourrait être une hausse, et rien en base ne permettait de
trancher : `cached_input_tokens` était calculé à chaque appel pour estimer le
coût, puis jeté.

Ce script lit la colonne. Il ne corrige rien et n'écrit rien.

⚠️ Les lignes ANTÉRIEURES à la migration valent 0 et écrasent la moyenne vers le
bas. `--jours` doit viser après le déploiement du 2026-08-27, sinon le rapport
annonce un cache inexistant. Le script refuse de conclure tant que la fenêtre
couvre des lignes d'avant.

Usage :
    python3 scripts/audit_cache_prompt.py
    python3 scripts/audit_cache_prompt.py --db data/wally.db --jours 7
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

# Le déploiement de la colonne. Une ligne plus ancienne porte 0 parce que
# personne ne l'a écrite, pas parce que le cache a raté.
_DEPUIS = time.mktime((2026, 8, 27, 0, 0, 0, 0, 0, -1))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Taux de cache de prompt par usage (lecture seule)")
    ap.add_argument("--db", default="data/wally.db")
    ap.add_argument("--jours", type=int, default=7)
    args = ap.parse_args()

    depuis = time.time() - args.jours * 86400
    if depuis < _DEPUIS:
        print(f"⚠️  La fenêtre remonte avant le 2026-08-27 : les lignes d'avant "
              f"portent 0 par défaut et FAUSSENT le taux.\n"
              f"    Fenêtre ramenée au 2026-08-27.")
        depuis = _DEPUIS

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(cost_log)")}
    if "cached_input_tokens" not in colonnes:
        print("La colonne `cached_input_tokens` n'existe pas encore dans cette base.\n"
              "Elle est posée par la migration au BOOT du bot : redémarrer wally,\n"
              "puis relancer. (Un traceback sqlite3 ici ne voudrait dire que ça.)")
        sys.exit(1)
    rows = conn.execute(
        "SELECT purpose, model, COUNT(*) n, SUM(input_tokens) entree, "
        "SUM(cached_input_tokens) cache, SUM(cost_usd) cout "
        "FROM cost_log WHERE timestamp >= ? "
        "GROUP BY purpose, model ORDER BY cout DESC",
        (depuis,),
    ).fetchall()

    if not rows:
        print(f"Aucun appel depuis {args.jours} j dans {args.db}.")
        return

    print(f"{'usage':22} {'modèle':18} {'appels':>7} {'entrée':>10} "
          f"{'cache':>10} {'taux':>7} {'coût $':>9}")
    print("-" * 88)
    t_ent = t_cache = t_cout = 0
    for r in rows:
        ent, cache = int(r["entree"] or 0), int(r["cache"] or 0)
        t_ent += ent
        t_cache += cache
        t_cout += float(r["cout"] or 0)
        taux = f"{100 * cache / ent:5.1f}%" if ent else "    —"
        print(f"{(r['purpose'] or '')[:22]:22} {(r['model'] or '')[:18]:18} "
              f"{r['n']:7} {ent:10} {cache:10} {taux:>7} {float(r['cout'] or 0):9.3f}")
    print("-" * 88)
    taux = f"{100 * t_cache / t_ent:5.1f}%" if t_ent else "    —"
    print(f"{'TOTAL':41} {sum(r['n'] for r in rows):7} {t_ent:10} "
          f"{t_cache:10} {taux:>7} {t_cout:9.3f}")


if __name__ == "__main__":
    main()
