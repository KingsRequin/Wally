#!/usr/bin/env python3
"""Amorce le compteur « messages traités » avec l'historique du journal.

`state.message_count` est un compteur EN MÉMOIRE : il repart de zéro à chaque
redémarrage, et la vitrine du site public annonçait « 1 » un quart d'heure
après un rebuild. Il est désormais persisté dans `bot_state`, mais persister
un compteur ne rend pas son passé — d'où ce script, à passer UNE fois.

Ce qu'on peut compter honnêtement, et rien de plus :

  · Le journal de conversations (`logs/conversations/**/*.jsonl`) porte un
    enregistrement `message_in` par message perçu. Il a été mis en service le
    2026-06-23 (commit `e29fef36`) : **avant cette date rien n'a été
    enregistré**, et aucune table de la base ne porte le cumul. Le total amorcé
    est donc un PLANCHER, pas le vrai total de tous les temps.
  · `message_in` n'est écrit que pour les salons que Wally perçoit (côté
    Discord) et après le filtre anti-bots (côté Twitch). C'est précisément la
    définition de « traité par Wally » — et c'est un peu moins que ce que
    `message_count` compte, qui inclut tout ce qui arrive.

Usage :
    python3 scripts/amorcer_compteur_messages.py            # compte et montre
    python3 scripts/amorcer_compteur_messages.py --ecrire   # écrit dans la base
    python3 scripts/amorcer_compteur_messages.py --ecrire --forcer   # écrase

Le bot doit être ARRÊTÉ pendant l'écriture, sinon son propre rangement
périodique repose l'ancienne valeur cinq minutes plus tard.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sqlite3
import sys
import time

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_JOURNAL = _RACINE / "logs" / "conversations"
_BASE = _RACINE / "data" / "wally.db"
_CLE = "messages_traites_total"


def compter() -> tuple[int, dict[str, int], tuple[str, str] | None]:
    """Rend (total, répartition par plateforme, (premier jour, dernier jour))."""
    par_plateforme: collections.Counter[str] = collections.Counter()
    jours: set[str] = set()
    total = 0

    for fichier in sorted(_JOURNAL.rglob("*.jsonl")):
        # `logs/conversations/<plateforme>/<canal>/<jour>.jsonl` — la plateforme
        # est le premier segment sous la racine, pas le nom du fichier.
        rel = fichier.relative_to(_JOURNAL).parts
        plateforme = rel[0] if len(rel) > 1 else "?"
        vu_ce_jour = False
        with fichier.open(encoding="utf-8") as f:
            for ligne in f:
                try:
                    enr = json.loads(ligne)
                except json.JSONDecodeError:
                    # Une ligne tronquée (arrêt brutal en pleine écriture) ne
                    # doit pas faire échouer le décompte des 87 000 autres.
                    continue
                if enr.get("type") != "message_in":
                    continue
                total += 1
                par_plateforme[plateforme] += 1
                vu_ce_jour = True
        if vu_ce_jour:
            jours.add(fichier.stem)

    plage = (min(jours), max(jours)) if jours else None
    return total, dict(par_plateforme), plage


def lire_existant() -> int | None:
    if not _BASE.exists():
        return None
    conn = sqlite3.connect(f"file:{_BASE}?mode=ro", uri=True)
    try:
        ligne = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (_CLE,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None          # table absente : base d'une version antérieure
    finally:
        conn.close()
    if not ligne:
        return None
    try:
        return int(ligne[0])
    except (TypeError, ValueError):
        return None


def ecrire(valeur: int) -> None:
    conn = sqlite3.connect(_BASE)
    try:
        conn.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (_CLE, str(valeur), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ecrire", action="store_true", help="écrit dans la base")
    ap.add_argument("--forcer", action="store_true",
                    help="écrase une valeur existante (sinon on refuse)")
    args = ap.parse_args()

    if not _JOURNAL.is_dir():
        print(f"❌ {_JOURNAL} introuvable — rien à compter", file=sys.stderr)
        return 1

    total, par_plateforme, plage = compter()
    print(f"{total} messages perçus dans le journal de conversations")
    for nom, n in sorted(par_plateforme.items(), key=lambda kv: -kv[1]):
        print(f"   · {nom:10s} {n:>7}")
    if plage:
        print(f"   du {plage[0]} au {plage[1]}")
    print("⚠️  Plancher, pas total : le journal date du 2026-06-23, rien "
          "n'existe avant.")

    existant = lire_existant()
    if existant is not None:
        print(f"\nValeur déjà en base : {existant}")

    if not args.ecrire:
        print("\n(lecture seule — relancer avec --ecrire pour poser la valeur)")
        return 0

    if existant is not None and not args.forcer:
        print("\n❌ Une valeur existe déjà. `--forcer` pour l'écraser — mais "
              "sachez que l'écrasement PERD ce que le bot a compté depuis "
              "l'amorce.", file=sys.stderr)
        return 1

    ecrire(total)
    print(f"\n✅ `{_CLE}` = {total}")
    print("   Redémarrer le bot pour qu'il le relise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
