#!/usr/bin/env python3
"""Deux garde-fous ruff : une PORTE DURE, et un CLIQUET.

Pourquoi ce script existe, alors que `lint_types.py` et `lint_silences.py`
couvraient déjà la dette : `ruff` était installé sur la machine depuis des mois
sans avoir jamais été lancé une seule fois. Le jour où on l'a lancé, il a sorti
du premier coup un `NameError` de production —
`_solder_pari_sur_partie` rangeait sa tâche de fond dans `_stream_voice_tasks`,
qui est une variable LOCALE de `main()`. Le premier bilan de partie avec un pari
ouvert plantait, et le pari serait resté ouvert pour toujours avec les points
des viewers dedans. Le test censé couvrir ce câblage cherchait le NOM de la
fonction dans le source de `main.py` : vert de bout en bout.

mypy ne voyait rien (pas une erreur de type), les 5864 tests non plus. C'est le
trou que ce script bouche.

──────────────────────────────────────────────────────────────────────────────
PORTE DURE — zéro toléré, aujourd'hui comme demain
──────────────────────────────────────────────────────────────────────────────
Ces familles sont à ZÉRO sur `bot/`. Ce ne sont pas des questions de goût : un
signalement ici est un défaut, et il n'y a aucune dette à amortir. Donc pas de
cliquet — on refuse, point.

  · `F`      pyflakes : nom indéfini, import mort, variable assignée jamais lue.
             C'est `F821` qui a trouvé le `NameError` ci-dessus.
  · `PLE`    erreurs pylint (et non ses avis de style).
  · `T20`    `print()`. Le projet impose loguru ; un `print()` en prod n'atterrit
             nulle part et ne porte ni niveau ni horodatage.
  · `ASYNC1` appel BLOQUANT dans une coroutine (`time.sleep`, `requests`, un
             `open()` sur le réseau). Tout est asyncio ici : un seul de ces
             appels gèle Discord, Twitch, le vocal et le dashboard en même temps.

──────────────────────────────────────────────────────────────────────────────
CLIQUET — la dette peut baisser, jamais monter
──────────────────────────────────────────────────────────────────────────────
Familles où il existe un stock antérieur. Même principe que les deux autres
cliquets : on n'en corrige pas 76 d'un coup, on interdit le 77e.

  · `DTZ`    `datetime` naïf (`utcnow()`, `now()` sans fuseau). L'hôte est en
             UTC, l'application raisonne en `Europe/Paris` : comparer les deux
             donne des résultats faux de deux heures, sans jamais lever.
  · `ASYNC2` `pathlib` dans une coroutine — moins grave qu'un `ASYNC1`, mais
             c'est bien le disque qu'on touche depuis la boucle d'événements.
  · `B`      bugbear : `except ... : raise X` sans `from` (la cause d'origine
             disparaît du traceback), `zip()` sans `strict=` (la liste la plus
             courte tronque les autres EN SILENCE).

Usage :
    python3 scripts/lint_ruff.py            # vérifie (sortie 1 si dépassement)
    python3 scripts/lint_ruff.py --liste     # affiche les signalements
    python3 scripts/lint_ruff.py --maj       # abaisse le cliquet au compte réel
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"

_PORTE_DURE = ["F", "PLE", "T20", "ASYNC1"]
_CLIQUET = ["DTZ", "ASYNC2", "B"]

# `ASYNC109` reproche à une coroutine d'avoir un paramètre `timeout` : c'est un
# conseil TRIO (« prends plutôt un cancel scope »), et il n'a pas de sens ici.
# Les deux sites visés — `self_fix._await_reaction`, `self_upgrade` — passent
# leur `timeout` directement à `bot.wait_for()` de discord.py, qui est l'idiome
# asyncio correct. Une porte dure qui crie à tort finit contournée, donc on la
# tient honnête plutôt que de la désarmer.
_IGNORE = ["ASYNC109"]


def _mesurer(regles: list[str]) -> tuple[int, str]:
    """Retourne (nombre de signalements, sortie lisible). -1 si ruff est absent."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "bot/",
             "--select", ",".join(regles), "--ignore", ",".join(_IGNORE),
             "--output-format", "concise", "--no-cache"],
            cwd=_RACINE, capture_output=True, text=True, timeout=300,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "ruff indisponible"
    if "No module named ruff" in (r.stderr or ""):
        return -1, "ruff indisponible"
    lignes = [ligne for ligne in r.stdout.splitlines() if ": " in ligne
              and not ligne.startswith(("Found", "warning:", "[*]"))]
    return len(lignes), "\n".join(lignes)


def _reference() -> dict:
    if not _REFERENCE.exists():
        return {}
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--liste", action="store_true", help="affiche les signalements")
    parser.add_argument("--maj", action="store_true", help="abaisse le cliquet au compte réel")
    args = parser.parse_args()

    dur, sortie_dur = _mesurer(_PORTE_DURE)
    if dur < 0:
        # Absence d'outil ≠ code propre. On le DIT, et on ne rend pas 0 : un
        # cliquet qui se tait quand son outil manque est pire que pas de cliquet.
        print("❌ ruff indisponible — `pip install ruff`.", file=sys.stderr)
        return 1

    souple, sortie_souple = _mesurer(_CLIQUET)
    seuil = int(_reference().get("max_ruff", 10**9))

    if args.liste:
        if sortie_dur:
            print("── porte dure ──")
            print(sortie_dur)
        if sortie_souple:
            print("── cliquet ──")
            print(sortie_souple)

    if args.maj:
        reference = _reference()      # FUSION : le fichier porte les trois cliquets
        reference["max_ruff"] = souple
        _REFERENCE.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        print(f"Cliquet ruff mis à jour : {souple}")
        return 0

    if dur > 0:
        print(
            f"❌ {dur} signalement(s) sur la PORTE DURE ({', '.join(_PORTE_DURE)}) — "
            "zéro toléré.\n"
            "   Nom indéfini, `print()`, ou appel bloquant dans une coroutine.\n"
            "   `python3 scripts/lint_ruff.py --liste` pour les emplacements.",
            file=sys.stderr,
        )
        return 1

    if souple > seuil:
        print(
            f"❌ {souple} signalements ruff, cliquet à {seuil} — "
            f"{souple - seuil} de trop.\n"
            f"   Familles surveillées : {', '.join(_CLIQUET)}.\n"
            "   `python3 scripts/lint_ruff.py --liste` pour les emplacements.",
            file=sys.stderr,
        )
        return 1

    if souple < seuil:
        print(
            f"✅ porte dure vide · {souple} signalements ruff (cliquet à {seuil}) — "
            f"{seuil - souple} de moins.\n"
            "   Pense à `--maj` pour verrouiller le progrès."
        )
        return 0

    print(f"✅ porte dure vide · {souple} signalements ruff — au niveau du cliquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
