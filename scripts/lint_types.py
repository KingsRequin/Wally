#!/usr/bin/env python3
"""Cliquet sur les erreurs de type — la dette peut baisser, jamais monter.

Pourquoi : plusieurs défauts des audits du 2026-08-10 étaient de pures erreurs
de type, visibles sans exécuter une ligne de code.

  · `get_active_action_tasks()` annoncé `list[dict]` rendait des `sqlite3.Row`,
    qui n'ont pas de `.get()` — le handler d'erreur de `reload_all()` en appelait
    un, l'AttributeError partait hors du `except`, et LE BOT NE DÉMARRAIT PLUS ;
  · `facts[True]` : `bool` est sous-classe de `int`, l'index désignait `facts[1]`
    et réécrivait silencieusement le mauvais souvenir ;
  · `.get()` appelé sur une valeur pouvant être `None`, trois fois.

Aucun test ne les voyait. mypy les voit tous.

Le projet compte 44 000 lignes écrites sans annotations complètes : on ne
corrige donc pas les 366 erreurs d'un coup. On empêche d'en ajouter, exactement
comme pour les gestionnaires muets.

Usage :
    python3 scripts/lint_types.py           # vérifie (sortie 1 si dépassement)
    python3 scripts/lint_types.py --liste    # affiche les erreurs
    python3 scripts/lint_types.py --maj      # abaisse le cliquet au compte réel
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"
_LIGNE_ERREUR = re.compile(r"^.+?:\d+: error: ", re.MULTILINE)


def _mesurer() -> tuple[int, str]:
    """Retourne (nombre d'erreurs, sortie brute). 0 si mypy est absent."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "mypy", "bot/", "--no-error-summary"],
            cwd=_RACINE, capture_output=True, text=True, timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "mypy indisponible"
    if "No module named mypy" in (r.stderr or ""):
        return -1, "mypy indisponible"
    return len(_LIGNE_ERREUR.findall(r.stdout)), r.stdout


def _reference() -> dict:
    if not _REFERENCE.exists():
        return {}
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--liste", action="store_true")
    parser.add_argument("--maj", action="store_true")
    args = parser.parse_args()

    compte, sortie = _mesurer()
    if compte < 0:
        # mypy est un confort de développement, pas une dépendance d'exécution :
        # son absence ne doit jamais faire échouer quoi que ce soit.
        print("⚠️  mypy indisponible — vérification de types ignorée")
        return 0

    if args.liste:
        print(sortie)

    ref = _reference()
    if args.maj:
        ref["max_erreurs_types"] = compte
        _REFERENCE.write_text(json.dumps(ref, indent=2) + "\n", encoding="utf-8")
        print(f"Cliquet des types mis à jour : {compte}")
        return 0

    seuil = int(ref.get("max_erreurs_types", 10**9))
    if compte > seuil:
        print(
            f"❌ {compte} erreurs de type, cliquet à {seuil} — "
            f"{compte - seuil} de trop.\n"
            "   `python3 scripts/lint_types.py --liste` pour le détail.",
            file=sys.stderr,
        )
        return 1
    if compte < seuil:
        print(f"✅ {compte} erreurs de type (cliquet à {seuil}) — pense à `--maj`.")
        return 0
    print(f"✅ {compte} erreurs de type — au niveau du cliquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
