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
un champ de format reçoit la variable liée par un `except ... as`, sans `!r`. Le
grep seul confondrait avec un `{e}` qui désigne un élément, un événement ou une
entrée.

⚠️ Les DEUX formes comptent, et l'oubli de la seconde a coûté un faux zéro :

    logger.warning("... {e}", e=exc)        # nommée   — 429 sites
    logger.warning("... {}", exc)           # positionnelle — 98 sites

Le premier passage ne regardait que la forme nommée. Le cliquet est resté à ZÉRO
une journée pendant que 98 sites en portaient encore : un garde-fou qui ne
couvre qu'une moitié du problème annonce « rien à signaler » sans mentir
techniquement. C'est la raison d'être de `_placeholders()` et de
`_spans_placeholders()` — comprendre les champs plutôt que chercher un motif.

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
from string import Formatter

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_SOURCE = _RACINE / "bot"
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"

_NIVEAUX = {"debug", "info", "success", "warning", "error", "critical", "exception", "log"}


def _placeholders(fmt: str) -> list[tuple[str | None, str | None, str | None]]:
    """Les champs de la chaîne, dans l'ordre : (nom, conversion, spec).

    `nom` vaut `""` pour un `{}` auto-numéroté, `"0"` pour un `{0}`, `"e"` pour
    un `{e}`. Les littéraux `{{` et `}}` n'en sont pas et ne comptent pas.
    """
    return [(nom, conv, spec) for _, nom, spec, conv in Formatter().parse(fmt)
            if nom is not None]


def _spans_placeholders(segment: str) -> list[tuple[int, int]]:
    """Les bornes (début, fin) de chaque champ DANS LE TEXTE SOURCE.

    On scanne à la main plutôt qu'au regex : il faut sauter les `{{`/`}}`
    échappés, et le segment peut enjamber plusieurs littéraux concaténés
    implicitement — auquel cas le texte entre eux ne porte que des guillemets
    et des blancs, jamais d'accolade.
    """
    spans, i, n = [], 0, len(segment)
    while i < n:
        c = segment[i]
        if c == "{":
            if i + 1 < n and segment[i + 1] == "{":
                i += 2
                continue
            fin = segment.find("}", i)
            if fin == -1:
                break
            spans.append((i, fin + 1))
            i = fin + 1
            continue
        if c == "}" and i + 1 < n and segment[i + 1] == "}":
            i += 2
            continue
        i += 1
    return spans


class _Chasseur(ast.NodeVisitor):
    """Repère les exceptions journalisées sans `!r`, nommées OU positionnelles.

    Les deux formes existent dans ce dépôt et souffrent du même mal :

        logger.warning("... {e}", e=exc)        # nommée
        logger.warning("... {}", exc)           # positionnelle

    La seconde a été oubliée au premier passage : le cliquet est resté à ZÉRO
    pendant que 98 sites en portaient encore. Un garde-fou qui ne regarde qu'une
    des deux formes annonce « rien à signaler » sans mentir techniquement.

    `_exc` est une PILE et non un simple nom : des `except` imbriqués lient des
    variables différentes, et n'en garder qu'une raterait celles du bloc
    extérieur une fois le bloc intérieur refermé.
    """

    def __init__(self) -> None:
        self._exc: list[str] = []
        # (nœud de la chaîne, rang du champ à corriger, ligne, niveau, étiquette)
        self.trouves: list[tuple[ast.Constant, int, int, str, str]] = []

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
            self._examiner(node, node.args[0], fn.attr)
        self.generic_visit(node)

    def _examiner(self, appel: ast.Call, fmt_node: ast.Constant, niveau: str) -> None:
        champs = _placeholders(fmt_node.value)
        positionnels = appel.args[1:]
        auto = 0
        for rang, (nom, conv, spec) in enumerate(champs):
            # Déjà converti (`{e!r}`), ou porteur d'une spec (`{:.0f}`) : on
            # n'y touche pas. Coller `!r` devant une spec numérique ferait
            # planter le formatage sur un objet qui n'est pas un nombre.
            if conv is not None or spec:
                if nom == "":
                    auto += 1
                continue
            if nom == "":                      # `{}` : le n-ième positionnel
                cible = positionnels[auto] if auto < len(positionnels) else None
                auto += 1
            elif nom.isdigit():                # `{0}` : explicitement le n-ième
                i = int(nom)
                cible = positionnels[i] if i < len(positionnels) else None
            else:                              # `{e}` : le mot-clé du même nom
                cible = next((k.value for k in appel.keywords if k.arg == nom), None)
            if isinstance(cible, ast.Name) and cible.id in self._exc:
                self.trouves.append((fmt_node, rang, appel.lineno, niveau, nom or "{}"))


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
        for _, _, ligne, niveau, etiquette in trouves:
            out.append(f"{f.relative_to(_RACINE)}:{ligne}  logger.{niveau}  {{{etiquette}}}")
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

        # Une chaîne peut porter PLUSIEURS champs à corriger (« {} illisible :
        # {} ») : on les regroupe par chaîne, et on traite les rangs du plus
        # grand au plus petit à l'intérieur.
        par_chaine: dict[tuple[int, int], set[int]] = {}
        for n, rang, _, _, _ in trouves:
            cle = (index(n.lineno, n.col_offset), index(n.end_lineno, n.end_col_offset))
            par_chaine.setdefault(cle, set()).add(rang)

        # De la FIN vers le DÉBUT : réécrire par l'avant décalerait toutes les
        # positions suivantes, et le remplacement d'après tomberait à côté.
        neuf, n_fichier = source, 0
        for (deb, fin), rangs in sorted(par_chaine.items(), reverse=True):
            segment = neuf[deb:fin]
            spans = _spans_placeholders(segment)
            for rang in sorted(rangs, reverse=True):
                if rang >= len(spans):
                    # Le rang vient de la chaîne JOINTE, les spans du texte
                    # source : un désaccord veut dire qu'on ne comprend pas ce
                    # segment. On s'abstient plutôt que de viser au hasard.
                    print(f"⚠️  {f}: champ {rang} introuvable dans le source, ignoré",
                          file=sys.stderr)
                    continue
                d, ff = spans[rang]
                champ = segment[d:ff]
                if "!" in champ or ":" in champ:
                    continue                    # déjà converti, ou porteur d'une spec
                segment = segment[:d] + champ[:-1] + "!r}" + segment[ff:]
                n_fichier += 1
            if segment != neuf[deb:fin]:
                neuf = neuf[:deb] + segment + neuf[fin:]

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
