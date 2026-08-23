#!/usr/bin/env python3
"""Les CVE des dépendances qui tournent VRAIMENT, c'est-à-dire dans l'image.

Pourquoi viser l'image et pas l'hôte. `requirements.txt` est en `>=` presque
partout : l'image reprend les dernières versions à chaque rebuild, tandis que
l'environnement Python de CT100 date de l'installation de la machine. Auditer
l'hôte donne donc une liste effrayante et FAUSSE — au premier passage,
`starlette 0.52.1` y portait six CVE alors que l'image tournait en 1.6.0, au
propre. Un rapport qui se trompe de cible fait perdre confiance à l'outil.

Le conteneur exécute `pip-audit` sur son propre environnement. Il n'y a rien à
installer sur l'hôte, et rien ne reste dans l'image (`--target` dans /tmp).

Usage :
    python3 scripts/audit_deps.py            # vérifie (sortie 1 si CVE)
    python3 scripts/audit_deps.py --brut      # la sortie complète de pip-audit
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

_SERVICE = "wally"

# Exceptions MOTIVÉES et DATÉES. Chaque entrée doit dire pourquoi la CVE ne
# s'applique pas ici, ou pourquoi on ne peut pas la corriger — sinon l'audit
# finit rouge en permanence, et un rapport toujours rouge n'est plus lu.
# À relire quand la contrainte amont bouge.
_EXCEPTIONS: dict[str, str] = {
    "PYSEC-2026-3002":
        "PyNaCl 1.5.0 / libsodium — `crypto_core_ed25519_is_valid_point` accepte "
        "des points hors du groupe principal. CVSS:3.1 AV:L/AC:H/C:L/I:L/A:N. "
        "Wally n'appelle JAMAIS cette primitive : PyNaCl ne sert ici qu'au "
        "chiffrement secretbox du vocal Discord. Et `discord.py[voice]` épingle "
        "`PyNaCl<1.6` jusqu'à la 2.7.1 incluse (la dernière au 2026-08-23) — "
        "monter la contrainte casse le build. À rouvrir dès que discord.py "
        "relâche cette borne.",
}
# `HOME` dans /tmp : l'utilisateur du conteneur (1000:1000) n'a pas le droit
# d'écrire dans `/home/wally/.cache`, et pip-audit y crée son cache AVANT de
# regarder quoi que ce soit — il mourait sur un `PermissionError`.
_DANS_LE_CONTENEUR = (
    "export HOME=/tmp && "
    "pip install -q --disable-pip-version-check --target /tmp/pa pip-audit 2>/dev/null && "
    "PYTHONPATH=/tmp/pa python /tmp/pa/bin/pip-audit "
    "  --progress-spinner off --format json 2>/dev/null"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brut", action="store_true", help="sortie complète de pip-audit")
    args = ap.parse_args()

    try:
        p = subprocess.run(
            ["docker", "compose", "exec", "-T", _SERVICE, "sh", "-c", _DANS_LE_CONTENEUR],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        print("❌ docker introuvable", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("❌ pip-audit n'a pas rendu la main en 10 min", file=sys.stderr)
        return 1

    if args.brut:
        print(p.stdout or p.stderr)

    try:
        rapport = json.loads(p.stdout)
    except json.JSONDecodeError:
        # Outil muet ≠ dépendances saines. Même règle que pour les cliquets :
        # on le dit, et on rend 1.
        print("❌ pip-audit n'a rien rendu d'exploitable. Le conteneur tourne-t-il ?\n"
              f"   {(p.stderr or p.stdout or '')[:300]}", file=sys.stderr)
        return 1

    total = len(rapport.get("dependencies", []))
    touches, excuses = [], []
    for d in rapport.get("dependencies", []):
        restantes = [v for v in d.get("vulns", []) if v["id"] not in _EXCEPTIONS]
        excusees = [v for v in d.get("vulns", []) if v["id"] in _EXCEPTIONS]
        if excusees:
            excuses.append((d, excusees))
        if restantes:
            touches.append({**d, "vulns": restantes})

    # Les exceptions se VOIENT à chaque passage. Une dérogation silencieuse
    # devient permanente : on la relit, ou on la retire.
    for d, vs in excuses:
        for v in vs:
            print(f"⚪ {d['name']} {d['version']} — {v['id']} : exception motivée")
            print(f"   {_EXCEPTIONS[v['id']]}")

    if not touches:
        print(f"✅ {total} paquets dans l'image, aucune CVE non traitée.")
        return 0

    print(f"❌ {len(touches)} paquet(s) vulnérable(s) sur {total} :", file=sys.stderr)
    for d in touches:
        corrige = sorted({v for vu in d["vulns"] for v in vu.get("fix_versions", [])})
        ids = ", ".join(sorted({vu["id"] for vu in d["vulns"]}))
        print(f"   · {d['name']} {d['version']} — {ids}"
              + (f"  → corrigé en {corrige[-1]}" if corrige else "  → aucun correctif publié"),
              file=sys.stderr)
    print("\n   `requirements.txt` est en `>=` : un rebuild suffit le plus souvent.\n"
          "   GIT_HASH=$(git rev-parse --short HEAD) BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \\\n"
          "     docker compose up -d --build wally", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
