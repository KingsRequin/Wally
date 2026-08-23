#!/usr/bin/env bash
# Garde-fou avant `git push` — les cliquets qu'on peut oublier de lancer.
#
# Posé par `python3 scripts/installer_hooks.py`. Il vit ICI, dans le dépôt,
# et pas seulement dans `.git/hooks/` : ce dernier n'est pas versionné, donc un
# hook qui n'existe que là disparaît au premier clone et personne ne le sait.
#
# Ce qu'il NE fait pas : la suite complète (55 s) et le smoke test navigateur
# (40 s). Un hook qui coûte deux minutes finit court-circuité par `--no-verify`,
# et un garde-fou contourné ne garde rien. Il lance les trois vérifications
# rapides ; les deux longues restent à la charge de la discipline, qui est déjà
# écrite dans le CLAUDE.md.
#
# Pour passer outre en connaissance de cause : `git push --no-verify`.
set -uo pipefail

# `git rev-parse` et PAS `dirname "$BASH_SOURCE"` : le hook est appelé par son
# LIEN dans `.git/hooks/`, donc `..` donnerait `.git/` et pas la racine. Écrit
# ainsi au premier jet, le hook refusait tout push en cherchant les cliquets
# dans `.git/scripts/` — un garde-fou rouge en permanence, qu'on aurait
# désactivé au bout de deux jours.
RACINE="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$RACINE" || exit 0

echo "── pre-push : cliquets rapides ──"
ECHECS=0
for c in lint_types lint_silences lint_ruff lint_logs; do
    if ! python3 "scripts/$c.py" >/tmp/prepush_$c.out 2>&1; then
        echo "❌ scripts/$c.py"
        sed 's/^/     /' /tmp/prepush_$c.out
        ECHECS=$((ECHECS + 1))
    else
        tail -1 /tmp/prepush_$c.out | sed 's/^/  /'
    fi
done

if [ "$ECHECS" -gt 0 ]; then
    cat >&2 <<'FIN'

Push refusé. Corrige, ou `git push --no-verify` si tu sais ce que tu fais.

Rappel : ce hook ne lance NI la suite complète (`python3 -m pytest tests/ -q`,
55 s) NI le smoke test du front (`python3 scripts/smoke_front.py`, 40 s). Les
deux restent obligatoires avant de déclarer une tâche terminée.
FIN
    exit 1
fi

echo "  ✅ les quatre cliquets passent"
exit 0
