#!/usr/bin/env python3
"""Pose les hooks git du dépôt dans `.git/hooks/`.

`.git/hooks/` n'est pas versionné : un hook qui n'existe que là disparaît au
premier clone, et rien ne le signale. Les hooks vivent donc dans `scripts/`, et
ce script les y branche par un lien symbolique — de sorte qu'une modification du
hook versionné prenne effet sans réinstallation.

Usage :
    python3 scripts/installer_hooks.py           # pose
    python3 scripts/installer_hooks.py --etat     # dit ce qui est en place
    python3 scripts/installer_hooks.py --retirer  # enlève
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_HOOKS = _RACINE / ".git" / "hooks"

# nom du hook git -> script versionné qui l'implémente
_POSES = {"pre-push": _RACINE / "scripts" / "hook_pre_push.sh"}


def _etat() -> int:
    for nom, source in _POSES.items():
        cible = _HOOKS / nom
        if not cible.exists() and not cible.is_symlink():
            print(f"  ⚪ {nom} — absent")
        elif cible.is_symlink() and cible.resolve() == source.resolve():
            print(f"  ✅ {nom} → {source.relative_to(_RACINE)}")
        else:
            print(f"  ⚠️  {nom} — présent mais ce n'est PAS le hook du dépôt")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--etat", action="store_true", help="dit ce qui est en place")
    ap.add_argument("--retirer", action="store_true", help="enlève les hooks")
    args = ap.parse_args()

    if not _HOOKS.is_dir():
        print(f"❌ {_HOOKS} introuvable — pas un dépôt git ?", file=sys.stderr)
        return 1

    if args.etat:
        return _etat()

    for nom, source in _POSES.items():
        cible = _HOOKS / nom
        if args.retirer:
            if cible.is_symlink() or cible.exists():
                cible.unlink()
                print(f"  retiré : {nom}")
            continue

        if cible.exists() and not cible.is_symlink():
            # On n'écrase JAMAIS un vrai fichier : il peut porter le travail de
            # quelqu'un d'autre, et un hook silencieusement remplacé est
            # exactement le genre de perte qu'on ne remarque pas.
            print(f"  ⚠️  {nom} existe déjà et n'est pas un lien — laissé tel quel",
                  file=sys.stderr)
            continue

        if cible.is_symlink():
            cible.unlink()
        os.chmod(source, 0o755)
        cible.symlink_to(source)
        print(f"  posé : {nom} → {source.relative_to(_RACINE)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
