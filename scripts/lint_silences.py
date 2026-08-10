#!/usr/bin/env python3
"""Refuse les nouveaux gestionnaires d'exception MUETS.

Pourquoi ce script existe : sur les 171 défauts corrigés lors des deux audits du
2026-08-10, la moitié partageait exactement la même signature — quelque chose
échoue, personne n'est prévenu, et le défaut vit des semaines. Le ménage nocturne
resté stub sept semaines, le ResponseGate qui n'a jamais lu un seul fait de
relation, quinze journées de journal remplacées par un message d'erreur, le
SpeakGuard qui n'a jamais bloqué : aucun de ces cas n'a produit la moindre ligne
de log.

Le problème n'est donc pas le bug, c'est son INVISIBILITÉ. Les tests ne le voient
pas — un `except: pass` passe tous les tests du monde. C'est au niveau du texte
qu'il faut l'attraper.

Un gestionnaire est considéré comme légitime s'il fait AU MOINS une de ces
choses :
  · journaliser (`logger.…`) — on saura que c'est arrivé ;
  · relever (`raise`) — l'appelant décidera ;
  · rendre un repli explicite (`return`) — le comportement est choisi, pas subi ;
  · porter un commentaire sur sa ligne ou juste au-dessus — quelqu'un a écrit
    POURQUOI le silence est le bon choix ici.

Le compte actuel sert de CLIQUET : on ne corrige pas 157 handlers d'un coup,
mais on interdit d'en ajouter un seul de plus. Quand la dette baisse, le seuil
baisse avec elle (`--maj` réécrit la référence).

Usage :
    python3 scripts/lint_silences.py            # vérifie (code de sortie 1 si dépassement)
    python3 scripts/lint_silences.py --liste     # affiche les emplacements
    python3 scripts/lint_silences.py --maj       # abaisse le cliquet au compte réel
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_SOURCE = _RACINE / "bot"
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"


def _est_muet(node: ast.ExceptHandler, lignes: list[str]) -> bool:
    """Vrai si ce gestionnaire avale l'erreur sans rien en dire ni en faire."""
    corps = ast.dump(node)
    if "logger" in corps:
        return False
    for enfant in ast.walk(node):
        if isinstance(enfant, (ast.Raise, ast.Return)):
            return False
        # Un repli EXPLICITE — `valeur = None`, `mode = "degrade"` — n'est pas un
        # silence : l'échec devient une donnée que l'appelant peut tester. C'est
        # ce que la règle annonçait depuis le début, mais que ce contrôle
        # n'implémentait pas : 45 des 158 signalements étaient de ce type, soit
        # 28 % de bruit. Un garde-fou qui crie à tort finit contourné.
        # `AugAssign` volontairement exclu : `compteur += 1` est de la
        # comptabilité, pas une valeur de repli.
        if isinstance(enfant, (ast.Assign, ast.AnnAssign)):
            return False
    # Un commentaire sur la ligne de l'`except` ou juste au-dessus vaut
    # justification : quelqu'un a pris la peine d'écrire pourquoi.
    i = node.lineno - 1
    contexte = " ".join(lignes[max(0, i - 1):i + 1])
    return "#" not in contexte


def recenser() -> list[str]:
    """Les emplacements `fichier:ligne` des gestionnaires muets, triés."""
    trouves: list[str] = []
    for fichier in sorted(_SOURCE.rglob("*.py")):
        source = fichier.read_text(encoding="utf-8")
        lignes = source.split("\n")
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(arbre):
            if isinstance(node, ast.ExceptHandler) and _est_muet(node, lignes):
                trouves.append(f"{fichier.relative_to(_RACINE)}:{node.lineno}")
    return trouves


def _cliquet() -> int:
    if not _REFERENCE.exists():
        return 10**9
    return int(json.loads(_REFERENCE.read_text(encoding="utf-8"))["max_silences"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--liste", action="store_true", help="affiche les emplacements")
    parser.add_argument("--maj", action="store_true", help="abaisse le cliquet au compte réel")
    args = parser.parse_args()

    trouves = recenser()
    seuil = _cliquet()

    if args.liste:
        for t in trouves:
            print(t)

    if args.maj:
        # FUSION, pas remplacement : le fichier porte aussi le cliquet des types
        # (`lint_types.py`). L'écraser effaçait silencieusement l'autre seuil, et
        # la vérification correspondante repassait au vert sans rien vérifier.
        reference = (
            json.loads(_REFERENCE.read_text(encoding="utf-8"))
            if _REFERENCE.exists() else {}
        )
        reference["max_silences"] = len(trouves)
        _REFERENCE.write_text(
            json.dumps(reference, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Cliquet mis à jour : {len(trouves)}")
        return 0

    if len(trouves) > seuil:
        print(
            f"❌ {len(trouves)} gestionnaires muets, cliquet à {seuil} — "
            f"{len(trouves) - seuil} de trop.\n"
            "   Un `except` doit journaliser, relever, rendre un repli, ou porter\n"
            "   un commentaire disant pourquoi le silence est le bon choix ici.\n"
            "   `python3 scripts/lint_silences.py --liste` pour les emplacements.",
            file=sys.stderr,
        )
        return 1

    if len(trouves) < seuil:
        print(
            f"✅ {len(trouves)} gestionnaires muets (cliquet à {seuil}) — "
            f"{seuil - len(trouves)} de moins.\n"
            "   Pense à `--maj` pour verrouiller le progrès."
        )
        return 0

    print(f"✅ {len(trouves)} gestionnaires muets — au niveau du cliquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
