#!/usr/bin/env python3
"""Rattrape les personnes qui ont des faits mais aucune ligne `memory_users`.

Mesuré le 2026-09-17 : 54 identités dans ce cas. `memory_users` n'était posé
que par les handlers de RÉPONSE (Discord et Twitch) ; tout ce qui écrit un fait
ailleurs l'oubliait :

  · l'import d'archives PhantomBot (45 comptes Twitch, dont `twitch:502342016`
    et ses 383 faits) ;
  · la perception passive Discord et les descriptions d'images (7 comptes) ;
  · des pseudos provisoires `unknown:` (3).

Sans cette ligne, la personne est absente de `list_memory_users()` : de la
liste des personnes du dashboard, et de la vérification du sujet d'un fait par
le FactExtractor. `SQLiteFactStore` la garantit désormais à l'écriture ; ce
script solde l'existant.

Il solde aussi trois restes de la même famille, antérieurs au correctif :

  · des lignes `memory_users` à l'id BRUT (`610550333042589752`, ou
    `unknown:925…`), doublons d'une ligne `discord:…` existante. Les brutes
    vidaient la liste des tiers du FactExtractor à chaque extraction ;
  · des alias dont l'uid canonique n'a pas de namespace et ne désigne
    personne (uid inventé par le LLM avant la garde de `fact_extractor`) ;
  · des portraits sans fait ni personne derrière eux.

Pseudo retenu, du plus fiable au moins fiable : le dernier nom sous lequel la
personne a écrit (journaux de conversation) · le nom le plus fréquent de ses
alias · le sujet le plus fréquent de ses faits. Les `unknown:` gardent un
pseudo NULL, comme toutes les lignes de ce namespace. `wally:` n'est personne.

Idempotent (`INSERT OR IGNORE`, suppressions ciblées), sûr bot en marche
(base en WAL, une transaction courte). Le cache d'alias en RAM ne relit la
table qu'au démarrage : appliquer AVANT le rebuild, puis relancer l'aperçu,
qui doit être vide.

    python3 scripts/rattraper_memory_users.py              # aperçu
    python3 scripts/rattraper_memory_users.py --appliquer
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from bot.db.mixins.memory import MemoryMixin  # noqa: E402


def _epoch(iso: str) -> float:
    """Colonnes de faits = UTC naïf."""
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()


def _noms_des_journaux(dossier: Path, bruts: set[str]) -> dict[str, tuple[float, str]]:
    """Dernier nom (et sa date) sous lequel chaque id brut a écrit."""
    vus: dict[str, tuple[float, str]] = {}
    if not bruts or not dossier.is_dir():
        return vus
    aiguilles = {f'"author_id": "{b}"': b for b in bruts}
    for fichier in dossier.rglob("*.jsonl"):
        with fichier.open(encoding="utf-8", errors="replace") as f:
            for ligne in f:
                brut = next((b for a, b in aiguilles.items() if a in ligne), None)
                if brut is None:
                    continue
                try:
                    evt = json.loads(ligne)
                except json.JSONDecodeError as e:
                    print(f"  ⚠️  ligne illisible dans {fichier} : {e!r}")
                    continue
                nom = str(evt.get("author") or "").split(" (@", 1)[0].strip()
                ts = float(evt.get("ts") or 0.0)
                if nom and ts >= vus.get(brut, (0.0, ""))[0]:
                    vus[brut] = (ts, nom)
    return vus


def _plus_frequent(valeurs: list[str | None]) -> str | None:
    propres = [v.strip() for v in valeurs if v and v.strip()]
    return Counter(propres).most_common(1)[0][0] if propres else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit vraiment (sans ce drapeau : simple aperçu)")
    ap.add_argument("--base", default=str(RACINE / "data" / "wally.db"))
    ap.add_argument("--journaux", default=str(RACINE / "logs" / "conversations"))
    args = ap.parse_args()

    c = sqlite3.connect(args.base, timeout=30)

    # ── 1. Personnes avec faits, sans ligne memory_users ─────────────────────
    manquants = c.execute(
        "SELECT f.user_id, COUNT(*), MAX(f.created_at) FROM atomic_facts f "
        "WHERE f.user_id NOT LIKE 'wally:%' AND NOT EXISTS "
        "  (SELECT 1 FROM memory_users m WHERE m.user_id = f.user_id) "
        "GROUP BY f.user_id ORDER BY COUNT(*) DESC"
    ).fetchall()
    bruts = {uid.split(":", 1)[1] for uid, _, _ in manquants
             if not uid.startswith("unknown:")}
    journaux = _noms_des_journaux(Path(args.journaux), bruts)

    a_creer: list[tuple[str, str, float, str | None]] = []
    incoherents: list[str] = []
    print(f"PERSONNES AVEC FAITS SANS memory_users : {len(manquants)}")
    for uid, nb, dernier in manquants:
        platform = uid.split(":", 1)[0]
        if MemoryMixin._fix_platform(uid, platform)[0] != uid:
            incoherents.append(uid)
            continue
        vu_le = _epoch(dernier)
        pseudo: str | None = None
        origine = "—"
        if platform != "unknown":
            brut = uid.split(":", 1)[1]
            alias = _plus_frequent([r[0] for r in c.execute(
                "SELECT display_name FROM user_aliases WHERE canonical_uid = ?", (uid,))])
            sujet = _plus_frequent([r[0] for r in c.execute(
                "SELECT subject FROM atomic_facts WHERE user_id = ?", (uid,))])
            if brut in journaux:
                vu_le = max(vu_le, journaux[brut][0])
                pseudo, origine = journaux[brut][1], "journal"
            elif alias:
                pseudo, origine = alias, "alias"
            elif sujet:
                pseudo, origine = sujet, "sujet"
        a_creer.append((uid, platform, vu_le, pseudo))
        jour = datetime.fromtimestamp(vu_le, timezone.utc).date().isoformat()
        print(f"  {uid:<32} {nb:>5} fait(s)  vu {jour}  pseudo={pseudo!r} ({origine})")
    if incoherents:
        print(f"  ⚠️  {len(incoherents)} uid à la plateforme incohérente, NON créés : "
              f"{', '.join(incoherents)}")

    # ── 2. Lignes memory_users à l'id brut, doublons d'une ligne namespacée ──
    # Brut (`610…`) ou déguisé en pseudo provisoire (`unknown:925…`) : un
    # snowflake n'est pas un pseudo. Retirée seulement si un compte
    # `discord:`/`twitch:` tient déjà cet id et qu'aucun fait n'y est rangé.
    brut_sql = ("CASE WHEN m.user_id LIKE 'unknown:%' THEN substr(m.user_id, 9) "
                "ELSE m.user_id END")
    candidats = c.execute(
        f"SELECT m.user_id, {brut_sql} FROM memory_users m "  # noqa: S608 — SQL constant
        "WHERE (instr(m.user_id, ':') = 0 OR m.user_id LIKE 'unknown:%') "
        f"AND {brut_sql} <> '' AND {brut_sql} NOT GLOB '*[^0-9]*' "
        "AND NOT EXISTS (SELECT 1 FROM atomic_facts f WHERE f.user_id = m.user_id)"
    ).fetchall()
    doublons: list[tuple[str, str]] = []
    sans_jumeau: list[str] = []
    for uid, brut in candidats:
        jumeau = c.execute(
            "SELECT user_id FROM memory_users WHERE user_id IN (?, ?)",
            (f"discord:{brut}", f"twitch:{brut}"),
        ).fetchone()
        if jumeau:
            doublons.append((uid, jumeau[0]))
        else:
            sans_jumeau.append(uid)
    print(f"\nLIGNES memory_users À L'ID BRUT (doublons à retirer) : {len(doublons)}")
    for uid, jumeau in doublons:
        print(f"  {uid}  (déjà tenu par {jumeau})")
    if sans_jumeau:
        print(f"  ⚠️  {len(sans_jumeau)} ligne(s) brute(s) SANS jumeau, laissées en place : "
              f"{', '.join(sans_jumeau)}")

    # ── 3. Alias vers un uid sans namespace qui ne désigne personne ──────────
    alias_morts = c.execute(
        "SELECT a.nickname, a.canonical_uid FROM user_aliases a "
        "WHERE instr(a.canonical_uid, ':') = 0 "
        "AND NOT EXISTS (SELECT 1 FROM memory_users m WHERE m.user_id LIKE '%:' || a.canonical_uid) "
        "AND NOT EXISTS (SELECT 1 FROM atomic_facts f WHERE f.user_id LIKE '%:' || a.canonical_uid)"
    ).fetchall()
    print(f"\nALIAS VERS UN UID INEXISTANT SANS NAMESPACE (à retirer) : {len(alias_morts)}")
    for nick, uid in alias_morts:
        print(f"  « {nick} » → {uid}")

    # ── 4. Portraits sans fait ni personne (après l'étape 1) ─────────────────
    crees = {uid for uid, *_ in a_creer}
    portraits_morts = [
        uid for (uid,) in c.execute(
            "SELECT p.user_id FROM user_profiles p "
            "WHERE NOT EXISTS (SELECT 1 FROM memory_users m WHERE m.user_id = p.user_id) "
            "AND NOT EXISTS (SELECT 1 FROM atomic_facts f WHERE f.user_id = p.user_id)")
        if uid not in crees
    ]
    print(f"\nPORTRAITS SANS FAIT NI PERSONNE (à retirer) : {len(portraits_morts)}")
    for uid in portraits_morts:
        print(f"  {uid}")

    if not args.appliquer:
        print("\naperçu — relancer avec --appliquer pour écrire")
        return 0

    with c:
        ecrits = sum(
            c.execute(
                "INSERT OR IGNORE INTO memory_users(user_id, platform, last_updated, username) "
                "VALUES (?, ?, ?, ?)", ligne,
            ).rowcount
            for ligne in a_creer
        )
        retires = sum(c.execute("DELETE FROM memory_users WHERE user_id = ?", (uid,)).rowcount
                      for uid, _ in doublons)
        alias_retires = sum(
            c.execute("DELETE FROM user_aliases WHERE nickname = ? AND canonical_uid = ?",
                      (nick, uid)).rowcount
            for nick, uid in alias_morts
        )
        portraits_retires = sum(
            c.execute("DELETE FROM user_profiles WHERE user_id = ?", (uid,)).rowcount
            for uid in portraits_morts
        )
    print(f"\nÉcrit : {ecrits} personne(s) créée(s), {retires} doublon(s) brut(s) retiré(s), "
          f"{alias_retires} alias mort(s) retiré(s), {portraits_retires} portrait(s) retiré(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
