#!/usr/bin/env python3
"""Le même filet que `lint_ruff.py`, mais sur le FRONT — où il n'y en avait aucun.

Pourquoi ce script existe : le projet a trois cliquets (`pytest`, `lint_types`,
`lint_silences`) et ils lisent tous les trois du Python. Or l'essentiel des
défauts récents vit dans l'overlay et le dashboard, c'est-à-dire dans 16 000
lignes de JavaScript que rien ne relisait — pas de `package.json`, pas de
linter, `node --check` au mieux, qui ne voit que la syntaxe.

Ce que le premier passage a trouvé, dans du code qui tournait en production :

  · `overlay_admin.js` — un bloc de quatre lignes greffé À L'INTÉRIEUR du
    `if (!autres.length)` de `propager()`, avec un `r` qui n'existe pas dans
    cette portée. Propager un placement depuis une scène unique levait
    `ReferenceError` au lieu d'afficher « il n'y a nulle part où propager ».
    C'est le découpage par hunks que le CLAUDE.md interdit, pris sur le fait.
  · `app.js` — `_renderParametresVoice()` appelait `makeFormRow()`, définie
    dans trois AUTRES fonctions et dans aucune portée englobante. Le panneau
    Paramètres → Vocal se vidait puis levait, sans un mot.

Aucun test ne les voyait : les tests JS du projet lisent les fichiers en TEXTE.

──────────────────────────────────────────────────────────────────────────────
PORTE DURE — zéro toléré
──────────────────────────────────────────────────────────────────────────────
`no-undef` est le `F821` du JavaScript, et c'est lui qui a sorti les deux bugs
ci-dessus. Le reste de la liste est du même tonneau : des choses qui ne sont
jamais volontaires. Aucune n'est une question de goût, et le compte est à zéro
— donc pas de cliquet, on refuse.

──────────────────────────────────────────────────────────────────────────────
CLIQUET — la dette peut baisser, jamais monter
──────────────────────────────────────────────────────────────────────────────
`no-empty` sur un `catch` : un bloc VIDE, sans même un commentaire. C'est
exactement la définition que `lint_silences.py` applique au Python, et le
pendant JS de la signature de défaut n°1 du projet — quelque chose échoue,
personne n'est prévenu, ça vit des semaines.

⚠ `no-unused-vars` est éteint (`.oxlintrc.json`), et ce n'est pas un
renoncement. Deux raisons mesurées :
  · une quarantaine de fonctions de `app.js` sont câblées depuis des
    `onclick="..."` dans du HTML construit en chaîne — le linter ne peut pas
    les voir, elles sont pourtant bien appelées ;
  · sur les 22 `catch (e)` à paramètre inutilisé qu'il signalait, l'échantillon
    relu à la main en donnait 8 sur 8 LÉGITIMES — repli explicite, notification
    à l'utilisateur, ou commentaire justifiant le silence.
Un garde-fou qui crie à tort finit contourné : c'est la leçon déjà payée sur
`lint_silences.py` (45 des 158 signalements étaient du bruit, soit 28 %).

Usage :
    python3 scripts/lint_js.py            # vérifie (sortie 1 si dépassement)
    python3 scripts/lint_js.py --liste     # affiche les signalements
    python3 scripts/lint_js.py --maj       # abaisse le cliquet au compte réel
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"

_CIBLES = ["bot/dashboard/static/", "public-ui/", "extension-musique/"]

# Des choses qui ne sont jamais voulues. `no-undef` en tête : c'est le `F821`
# du JS, et il a trouvé deux bugs vivants au premier passage.
_PORTE_DURE = [
    "no-undef", "no-dupe-keys", "no-dupe-class-members", "no-dupe-else-if",
    "no-duplicate-case", "no-func-assign", "no-import-assign", "no-obj-calls",
    "no-self-assign", "no-self-compare", "no-sparse-arrays",
    "no-unsafe-negation", "no-unsafe-optional-chaining", "use-isnan",
    "valid-typeof", "no-cond-assign", "no-constant-binary-expression",
    "no-debugger", "no-async-promise-executor", "getter-return",
    "no-setter-return", "no-new-native-nonconstructor",
]

_CLIQUET = ["no-empty"]

_SIGNALEMENT = re.compile(r"^\S+:\d+:\d+: (?:error|warning) ", re.MULTILINE)


def _fichiers() -> list[str]:
    """La liste EXPLICITE des `.js` à relire.

    On n'passe pas les dossiers à oxlint, pour deux raisons qui se cumulent :

      · `public-ui/` figure dans `.gitignore` (ses neuf fichiers sont pourtant
        suivis). oxlint honore le `.gitignore` et sautait donc TOUT LE SITE
        PUBLIC — en silence, en annonçant zéro défaut. C'est ce qui a rendu les
        deux premiers essais de mutation verts alors que le code était fautif.
      · `--no-ignore` ne rattrape pas le coup : oxc-project/oxc#21727, une
        marche d'arbre qui rend zéro fichier sans le dire.

    Une liste explicite ne peut pas mentir sur ce qu'elle n'a pas lu.
    """
    trouves: list[str] = []
    for cible in _CIBLES:
        for f in sorted((_RACINE / cible).rglob("*.js")):
            if "vendor" in f.parts or "node_modules" in f.parts:
                continue
            trouves.append(str(f.relative_to(_RACINE)))
    return trouves


def _oxlint(regles: list[str]) -> tuple[int, str]:
    """Retourne (nombre de signalements, sortie lisible). -1 si npx est absent.

    `-A all` puis `-D <règle>` : on éteint tout et on rallume nommément, sinon
    la catégorie `correctness` d'oxlint rallume au passage des règles de style
    que le projet a explicitement écartées.
    """
    if shutil.which("npx") is None:
        return -1, "npx indisponible"
    fichiers = _fichiers()
    if not fichiers:
        return -1, "aucun fichier .js trouvé"
    cmd = ["npx", "--yes", "oxlint@latest", "-A", "all"]
    for r in regles:
        cmd += ["-D", r]
    cmd += fichiers
    try:
        p = subprocess.run(cmd, cwd=_RACINE, capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "oxlint indisponible"
    sortie = p.stdout + p.stderr
    if "npm error" in sortie or "could not determine executable" in sortie:
        return -1, "oxlint indisponible"
    lignes = [ligne for ligne in sortie.splitlines() if _SIGNALEMENT.match(ligne)]
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

    dur, sortie_dur = _oxlint(_PORTE_DURE)
    if dur < 0:
        # Absence d'outil ≠ code propre. Même règle que pour mypy et ruff : on
        # le dit, et on rend 1. Un cliquet qui se tait quand son outil manque
        # est pire que pas de cliquet du tout.
        print("❌ oxlint injoignable — il faut Node et le réseau (`npx oxlint`).",
              file=sys.stderr)
        return 1

    souple, sortie_souple = _oxlint(_CLIQUET)
    seuil = int(_reference().get("max_js", 10**9))

    if args.liste:
        if sortie_dur:
            print("── porte dure ──")
            print(sortie_dur)
        if sortie_souple:
            print("── cliquet ──")
            print(sortie_souple)

    if args.maj:
        reference = _reference()      # FUSION : le fichier porte les quatre cliquets
        reference["max_js"] = souple
        _REFERENCE.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        print(f"Cliquet JS mis à jour : {souple}")
        return 0

    if dur > 0:
        print(
            f"❌ {dur} signalement(s) sur la PORTE DURE du front — zéro toléré.\n"
            "   Nom indéfini, clé dupliquée, `debugger` oublié, comparaison\n"
            "   impossible. `python3 scripts/lint_js.py --liste` pour les voir.",
            file=sys.stderr,
        )
        return 1

    if souple > seuil:
        print(
            f"❌ {souple} blocs vides, cliquet à {seuil} — {souple - seuil} de trop.\n"
            "   Un `catch` doit journaliser, rendre un repli, prévenir\n"
            "   l'utilisateur, ou porter un commentaire disant pourquoi le\n"
            "   silence est le bon choix ici.",
            file=sys.stderr,
        )
        return 1

    if souple < seuil:
        print(
            f"✅ porte dure vide · {souple} blocs vides (cliquet à {seuil}) — "
            f"{seuil - souple} de moins.\n"
            "   Pense à `--maj` pour verrouiller le progrès."
        )
        return 0

    print(f"✅ porte dure vide · {souple} blocs vides — au niveau du cliquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
