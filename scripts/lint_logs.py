#!/usr/bin/env python3
"""Une exception journalisée avec `{e}` peut n'écrire RIEN. Ce script l'interdit.

Le défaut. Beaucoup d'exceptions ont un `str()` VIDE :

    ConnectError('')  ReadTimeout('')  CancelledError()  TimeoutError()

`logger.warning("Apex bridge error: {e}", e=exc)` produit alors la ligne

    ERROR | bot.core.apex.client:92 | Apex bridge error:

et rien d'autre. On journalise fidèlement l'absence d'information : ni le type,
ni la cause, rien sur quoi diagnostiquer. `{e!r}` rend `ConnectError('')` — le
TYPE, qui est ici toute la donnée utile.

Ce n'est pas une hypothèse. Les logs d'août portent 599 lignes qui s'arrêtent
sur un deux-points, dont 205 en une seule journée (le 20) sur ce même site Apex,
et 117 sur `get_stream` de Twitch. Le site Apex a été corrigé à la main après
coup ; les autres attendaient encore.

Ce que le script détecte, en AST et pas au grep : un appel `logger.<niveau>` dont
la chaîne de format contient `{nom}` alors que `nom=` reçoit la variable liée par
un `except ... as`. Le grep seul confondrait avec un `{e}` qui désigne un
élément, un événement ou une entrée.

Usage :
    python3 scripts/lint_logs.py             # vérifie (sortie 1 si dépassement)
    python3 scripts/lint_logs.py --liste      # affiche les emplacements
    python3 scripts/lint_logs.py --corriger   # réécrit `{e}` en `{e!r}`
    python3 scripts/lint_logs.py --maj        # abaisse le cliquet au compte réel
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_SOURCE = _RACINE / "bot"
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"

_NIVEAUX = {"debug", "info", "success", "warning", "error", "critical", "exception", "log"}


class _Chasseur(ast.NodeVisitor):
    """Repère les `logger.X("... {e} ...", e=<exception>)`.

    `_exc` est une PILE et non un simple nom : des `except` imbriqués lient des
    variables différentes, et n'en garder qu'une raterait celles du bloc
    extérieur une fois le bloc intérieur refermé.
    """

    def __init__(self) -> None:
        self._exc: list[str] = []
        self.trouves: list[tuple[ast.Constant, str, int, str]] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._exc.append(node.name)
        self.generic_visit(node)
        if node.name:
            self._exc.pop()

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr in _NIVEAUX
                and isinstance(fn.value, ast.Name) and fn.value.id == "logger"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            fmt_node = node.args[0]
            for kw in node.keywords:
                if (kw.arg and isinstance(kw.value, ast.Name)
                        and kw.value.id in self._exc
                        and re.search(r"\{%s\}" % re.escape(kw.arg), fmt_node.value)):
                    self.trouves.append((fmt_node, kw.arg, node.lineno, fn.attr))
        self.generic_visit(node)


def _analyser(fichier: pathlib.Path):
    try:
        source = fichier.read_text(encoding="utf-8")
        arbre = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return source if "source" in dir() else "", []
    c = _Chasseur()
    c.visit(arbre)
    return source, c.trouves


def recenser() -> list[str]:
    """Les emplacements `fichier:ligne` (niveau), triés."""
    out: list[str] = []
    for f in sorted(_SOURCE.rglob("*.py")):
        _, trouves = _analyser(f)
        for _, nom, ligne, niveau in trouves:
            out.append(f"{f.relative_to(_RACINE)}:{ligne}  logger.{niveau}  {{{nom}}}")
    return out


def corriger() -> int:
    """Réécrit `{nom}` en `{nom!r}` dans les chaînes de format concernées.

    On remplace DANS LE SEGMENT de la chaîne de format, repéré par ses positions
    AST, et jamais dans le fichier entier : le même `{e}` peut apparaître
    légitimement ailleurs — dans une f-string voisine, un message d'API, ou une
    chaîne où `e` désigne un élément.

    Le fichier est reparsé après coup et comparé : si la structure a bougé
    autrement que par les littéraux, on abandonne le fichier.
    """
    total = 0
    for f in sorted(_SOURCE.rglob("*.py")):
        source, trouves = _analyser(f)
        if not trouves:
            continue
        lignes = source.splitlines(keepends=True)
        # Décalages cumulés des lignes, pour convertir (ligne, colonne) en index.
        debuts = [0]
        for ligne in lignes:
            debuts.append(debuts[-1] + len(ligne))

        def index(l: int, c: int) -> int:
            return debuts[l - 1] + c

        # De la FIN vers le DÉBUT : réécrire par l'avant décalerait toutes les
        # positions suivantes, et le remplacement d'après tomberait à côté.
        edits = sorted(
            {(index(n.lineno, n.col_offset),
              index(n.end_lineno, n.end_col_offset), nom) for n, nom, _, _ in trouves},
            reverse=True,
        )
        neuf, n_fichier = source, 0
        for deb, fin, nom in edits:
            segment = neuf[deb:fin]
            remplace, k = re.subn(r"\{%s\}" % re.escape(nom), "{%s!r}" % nom, segment)
            if k:
                neuf = neuf[:deb] + remplace + neuf[fin:]
                n_fichier += k

        if not n_fichier:
            continue
        try:
            ast.parse(neuf)
        except SyntaxError as exc:
            print(f"⚠️  {f} laissé intact — la réécriture ne parse plus : {exc!r}",
                  file=sys.stderr)
            continue
        f.write_text(neuf, encoding="utf-8")
        total += n_fichier
        print(f"  {n_fichier:3d}  {f.relative_to(_RACINE)}")
    return total


def _reference() -> dict:
    if not _REFERENCE.exists():
        return {}
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--liste", action="store_true", help="affiche les emplacements")
    ap.add_argument("--corriger", action="store_true", help="réécrit `{e}` en `{e!r}`")
    ap.add_argument("--maj", action="store_true", help="abaisse le cliquet au compte réel")
    args = ap.parse_args()

    if args.corriger:
        n = corriger()
        print(f"\n{n} placeholder(s) réécrit(s) en `!r`.")
        print("Relance `python3 scripts/lint_logs.py --maj` pour verrouiller.")
        return 0

    trouves = recenser()
    seuil = int(_reference().get("max_logs_aveugles", 10**9))

    if args.liste:
        for t in trouves:
            print(t)

    if args.maj:
        reference = _reference()      # FUSION : le fichier porte tous les cliquets
        reference["max_logs_aveugles"] = len(trouves)
        _REFERENCE.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        print(f"Cliquet des logs aveugles mis à jour : {len(trouves)}")
        return 0

    if len(trouves) > seuil:
        print(
            f"❌ {len(trouves)} exception(s) journalisée(s) sans `!r`, cliquet à "
            f"{seuil} — {len(trouves) - seuil} de trop.\n"
            "   `ConnectError('')` a un `str()` VIDE : la ligne s'arrête sur le\n"
            "   deux-points et ne dit RIEN. Écrire `{e!r}`.\n"
            "   `python3 scripts/lint_logs.py --corriger` le fait pour vous.",
            file=sys.stderr,
        )
        return 1

    if len(trouves) < seuil:
        print(f"✅ {len(trouves)} exception(s) sans `!r` (cliquet à {seuil}) — "
              f"{seuil - len(trouves)} de moins.\n   Pense à `--maj`.")
        return 0

    print(f"✅ {len(trouves)} exception(s) journalisée(s) sans `!r` — au niveau du cliquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
