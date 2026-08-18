#!/usr/bin/env python3
"""Retire les relevés Apex faussés par l'addition de deux trackers d'un libellé.

Du 2026-08-10 au 2026-08-18, `reader.py` additionnait les trackers portant le
même libellé (« BR Kills » chez Azraël : `specialEvent_kills` + `kills`). Les
relevés consignés dans `apex_stat_points` pendant cette fenêtre portent donc des
NIVEAUX faux — 104 381 kills pour Azraël qui en a 92 182, 28 712 pour IronAnanas
qui en a 16 048.

Ces niveaux ne sont pas redressables : on ne peut pas décomposer une somme a
posteriori sans savoir ce que valait chaque tracker à l'instant du relevé. On les
supprime, et seulement eux — un compte à tracker unique n'a jamais été faussé, ses
points sont justes et restent.

Chirurgical à deux niveaux : on interroge l'API compte par compte pour savoir
QUI a des doublons, puis notion par notion pour savoir LESQUELLES l'étaient.
`rank_score` ne vient pas d'un tracker (il est lu dans `global.rank`) : jamais
concerné.

    python3 scripts/purger_apex_points_additionnes.py            # simulation
    python3 scripts/purger_apex_points_additionnes.py --appliquer
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from bot.core.apex.reader import STAT_ALIASES

DB = Path(__file__).resolve().parent.parent / "data" / "wally.db"
# Le correctif est passé en production à cette date ; tout relevé antérieur a été
# écrit par le lecteur qui additionnait.
CORRECTIF_TS = 1787045000.0  # 2026-08-18 ~11:30 Europe/Paris


def _cle_api() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    for ligne in env.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("APEX_API_KEY="):
            return ligne.split("=", 1)[1].strip()
    return os.environ.get("APEX_API_KEY", "")


def _payload(cle: str, uid: str, plateforme: str) -> dict | None:
    """Le profil brut, ou None si l'API ne le rend pas."""
    reponse = httpx.get(
        "https://api.mozambiquehe.re/bridge",
        params={"uid": uid, "platform": plateforme},
        headers={"Authorization": cle},
        timeout=30,
    )
    if reponse.status_code != 200:
        return None
    data = reponse.json()
    return data if isinstance(data, dict) and data.get("total") else None


def _notions_doublees(payload: dict) -> set[str]:
    """Les notions dont ce compte publie PLUSIEURS trackers du même libellé.

    C'est exactement la condition qui déclenchait l'addition : un seul tracker
    par libellé n'a jamais pu être doublé.
    """
    par_libelle: dict[str, int] = {}
    for entree in (payload.get("total") or {}).values():
        if isinstance(entree, dict) and entree.get("name"):
            cle = str(entree["name"]).lower()
            par_libelle[cle] = par_libelle.get(cle, 0) + 1

    touchees = set()
    for notion, alias in STAT_ALIASES.items():
        if any(par_libelle.get(a.lower(), 0) > 1 for a in alias):
            touchees.add(notion)
    return touchees


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--appliquer", action="store_true",
                         help="écrit vraiment ; sans ce drapeau, simulation")
    args = parseur.parse_args()

    cle = _cle_api()
    if not cle:
        print("APEX_API_KEY introuvable — abandon.")
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # La plateforme vit dans `apex_profiles` ; sans elle l'API refuse la requête
    # (« Missing at least one of the following parameters »), uid ou pas.
    comptes = conn.execute(
        "SELECT DISTINCT p.uid, COALESCE(pr.platform, 'PC') AS platform "
        "FROM apex_stat_points p LEFT JOIN apex_profiles pr ON pr.uid = p.uid"
    ).fetchall()

    total_supprime = 0
    for compte in comptes:
        uid, plateforme = compte["uid"], compte["platform"]
        payload = _payload(cle, uid, plateforme)
        if payload is None:
            print(f"  {uid:18} — profil illisible, RIEN touché (on ne supprime pas à l'aveugle)")
            continue

        notions = _notions_doublees(payload)
        if not notions:
            print(f"  {uid:18} — un seul tracker par libellé, points intacts")
            continue

        marques = ",".join("?" for _ in notions)
        lignes = conn.execute(
            f"SELECT notion, COUNT(*) n FROM apex_stat_points "
            f"WHERE uid = ? AND recorded_at < ? AND notion IN ({marques}) "
            f"GROUP BY notion",
            (uid, CORRECTIF_TS, *sorted(notions)),
        ).fetchall()
        detail = ", ".join(f"{l['notion']}×{l['n']}" for l in lignes) or "rien à purger"
        compte_lignes = sum(l["n"] for l in lignes)
        print(f"  {uid:18} — doublons sur {sorted(notions)} → {detail}")

        if args.appliquer and compte_lignes:
            conn.execute(
                f"DELETE FROM apex_stat_points "
                f"WHERE uid = ? AND recorded_at < ? AND notion IN ({marques})",
                (uid, CORRECTIF_TS, *sorted(notions)),
            )
        total_supprime += compte_lignes

    if args.appliquer:
        conn.commit()
        print(f"\n{total_supprime} relevé(s) supprimé(s).")
    else:
        print(f"\nSimulation : {total_supprime} relevé(s) seraient supprimés. "
              f"Relancer avec --appliquer.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
