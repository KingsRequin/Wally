#!/usr/bin/env python3
"""Refuse le code mort neuf — fonctions, méthodes et paramètres jamais lus.

Pourquoi ce script existe : la « STEP 0 rule » du projet impose de purger le
code mort AVANT tout refactor structurel, parce qu'il accélère la compaction du
contexte. Sauf qu'aucun outil ne le MESURAIT : on le découvrait à la main, tard,
et par accident — 253 lignes de JS mort dans le panneau Twitch, découvertes
seulement parce qu'un ajout avait été greffé DEDANS et ne s'affichait pas.

Ruff ne suffit pas ici. Ses règles `F401`/`F841` sont INTRA-fichier : un import
inutilisé, une locale assignée puis oubliée. Une fonction publique que plus
personne n'appelle, une méthode devenue orpheline après un refactor, un
paramètre reçu et jamais lu — tout cela lui est invisible, parce que la réponse
demande de regarder le RESTE du dépôt.

Deux niveaux, parce que les signalements de vulture ne se valent pas :

  · confiance 100 — certitudes. Un paramètre ou une locale dont le nom
    n'apparaît nulle part ailleurs dans son propre scope. Pas d'interprétation
    possible. C'est ce niveau qui a trouvé `username_hint`, passé par CINQ
    appelants de production (Twitch, Discord ×2, /wally ask, chat web) et jamais
    lu par `MemoryService.search()` : cinq chemins qui envoyaient un indice de
    pseudo dans le vide, en silence, depuis des mois.

  · confiance 60 — soupçons. Attributs posés dynamiquement, champs de dataclass
    lus par PyYAML, handlers appelés par un décorateur : vulture ne voit pas ces
    appelants-là et crie souvent à tort. Le compte sert de CLIQUET, pas de
    verdict — on n'en ajoute pas, on ne prétend pas qu'ils sont tous morts.

⚠️ Les points d'entrée appelés par une BIBLIOTHÈQUE (`on_message`, `event_*`,
`do_GET`, `row_factory`…) sont désormais exclus — cf. `_APPELES_PAR_UNE_LIB`.
Ils comptaient pour 72 des 321 signalements du 2026-08-26 sans qu'aucun puisse
jamais être corrigé. Le cliquet a donc CHANGÉ DE DÉFINITION à cette date : les
chiffres d'avant ne se comparent pas à ceux d'après.

Le cliquet est la même mécanique que partout ailleurs dans `scripts/` : le
compte actuel fait référence, un dépassement échoue, et `--maj` ne sert QU'APRÈS
une baisse réelle de la dette.

Usage :
    python3 scripts/lint_mort.py            # vérifie (code de sortie 1 si dépassement)
    python3 scripts/lint_mort.py --liste     # affiche les signalements
    python3 scripts/lint_mort.py --maj       # abaisse les cliquets au compte réel
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_RACINE = pathlib.Path(__file__).resolve().parent.parent
_REFERENCE = _RACINE / "scripts" / "silences_cliquet.json"

# `bot` et `scripts` seulement. `tests/` est volontairement hors périmètre : une
# fonction de test n'est jamais « appelée » par du code, elle est collectée par
# pytest, et vulture signalerait la suite entière.
_CIBLES = ["bot", "scripts"]

# Ce que vulture ne PEUT pas voir appelé, et qu'il signale donc à tort.
#
# Ces noms sont des points d'entrée invoqués par NOM depuis une bibliothèque :
# aucun appel n'apparaît dans notre code, et il n'en apparaîtra jamais. Les
# compter, c'était noyer le vrai code mort dans du bruit — 72 signalements sur
# 321 au 2026-08-26, soit près d'un quart. La leçon est celle du jour : une
# mesure qui mélange bruit et signal envoie corriger au mauvais endroit.
#
# Le prix, assumé : une fonction VRAIMENT morte qui porterait un de ces noms
# passerait inaperçue. C'est peu probable — ces noms sont imposés par les libs,
# on n'en invente pas — et c'est moins cher qu'un compteur illisible.
_APPELES_PAR_UNE_LIB = (
    "on_*",            # discord.py : on_message, on_ready, on_member_join…
    "event_*",         # twitchio : event_ready, event_error, event_eventsub_*
    "setup_hook",      # discord.py
    "cog_*",           # discord.py
    "do_GET", "do_POST", "log_message",   # http.server.BaseHTTPRequestHandler
    "row_factory",     # sqlite3 : posé, jamais relu par nous
    "should_exit",     # uvicorn
)

# Les deux niveaux et la clé de cliquet qui va avec.
_NIVEAUX = (
    (100, "max_code_mort_certain", "certitudes"),
    (60, "max_code_mort", "soupçons"),
)


def recenser(confiance: int) -> list[str]:
    """Les signalements de vulture à ce niveau de confiance, triés.

    Rend des lignes `fichier:ligne: message`. Le tri vient de vulture lui-même
    (il parcourt les fichiers dans l'ordre) ; on le refait explicitement pour
    que deux exécutions sur la même arborescence donnent le même ordre, sans
    dépendre de ce détail d'implémentation.
    """
    resultat = subprocess.run(
        ["vulture", *_CIBLES, "--min-confidence", str(confiance),
         "--ignore-names", ",".join(_APPELES_PAR_UNE_LIB)],
        cwd=_RACINE,
        capture_output=True,
        text=True,
    )
    # vulture rend 3 quand il a trouvé du code mort, 0 quand il n'a rien trouvé.
    # Tout autre code est une VRAIE panne (cible absente, erreur de syntaxe) et
    # doit remonter : un outil qui rend zéro sans avoir rien lu est le piège que
    # ce dépôt a déjà payé une fois.
    if resultat.returncode not in (0, 3):
        raise RuntimeError(
            f"vulture a échoué (code {resultat.returncode}) : {resultat.stderr.strip()!r}"
        )
    return sorted(ligne for ligne in resultat.stdout.splitlines() if ligne.strip())


def _cliquets() -> dict:
    if not _REFERENCE.exists():
        return {}
    return json.loads(_REFERENCE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--liste", action="store_true", help="affiche les signalements")
    parser.add_argument("--maj", action="store_true", help="abaisse les cliquets au compte réel")
    args = parser.parse_args()

    reference = _cliquets()
    comptes: dict[str, int] = {}
    depassements: list[str] = []
    progres: list[str] = []

    for confiance, cle, libelle in _NIVEAUX:
        trouves = recenser(confiance)
        comptes[cle] = len(trouves)

        if args.liste:
            print(f"─── confiance {confiance} ({libelle}) : {len(trouves)} ───")
            for t in trouves:
                print(t)

        if args.maj:
            continue
        seuil = reference.get(cle)
        if seuil is None:
            # Un cliquet absent ne doit JAMAIS valoir « rien à signaler ». C'est
            # la panne silencieuse que tout ce dossier existe pour empêcher : la
            # vérification passerait au vert sans avoir comparé quoi que ce soit,
            # et personne ne le saurait.
            depassements.append(
                f"   · confiance {confiance} ({libelle}) : aucun cliquet `{cle}` dans "
                f"{_REFERENCE.name} — rien n'est vérifié. `--maj` pour le poser."
            )
            continue
        if len(trouves) > seuil:
            depassements.append(
                f"   · confiance {confiance} ({libelle}) : {len(trouves)} pour un "
                f"cliquet à {seuil} — {len(trouves) - seuil} de trop."
            )
        elif len(trouves) < seuil:
            progres.append(
                f"   · confiance {confiance} ({libelle}) : {len(trouves)} pour un "
                f"cliquet à {seuil} — {seuil - len(trouves)} de moins."
            )

    if args.maj:
        # FUSION, pas remplacement : ce fichier porte AUSSI les cliquets des
        # silences, des types, de ruff, du JS et des logs. L'écraser ferait
        # repasser les autres vérifications au vert sans rien vérifier — le
        # piège est écrit noir sur blanc dans `lint_silences.py`, il a coûté
        # assez cher pour ne pas être refait ici.
        reference.update(comptes)
        _REFERENCE.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
        print("Cliquets mis à jour : " + ", ".join(f"{c}={n}" for c, n in comptes.items()))
        return 0

    if depassements:
        print(
            "❌ Code mort en hausse :\n"
            + "\n".join(depassements)
            + "\n   Une fonction que personne n'appelle, un paramètre que personne ne lit :\n"
            "   soit on le branche, soit on le retire. `--liste` pour les emplacements.",
            file=sys.stderr,
        )
        return 1

    if progres:
        print("✅ Code mort en baisse :\n" + "\n".join(progres) + "\n   Pense à `--maj` pour verrouiller le progrès.")
        return 0

    print(
        "✅ Code mort au niveau des cliquets ("
        + ", ".join(f"{n} à {c}" for (c, _, _), n in zip(_NIVEAUX, comptes.values()))
        + ")."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
