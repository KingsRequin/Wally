#!/usr/bin/env python3
"""Nettoyage one-shot de la dette mentale de Wally (Phase 5 — vie mentale).

Dédup des DESIRE quasi-identiques, élagage des THOUGHT quasi-doublons, et
marquage d'une liste curée de pseudo-souvenirs confirmés faux. Tout est
RÉVERSIBLE (archive / needs_review, jamais de suppression) et idempotent (on ne
traite que les faits `active`).

Le clustering est DÉTERMINISTE : similarité Jaccard pondérée par la rareté des
tokens (IDF). Les vrais doublons partagent des tokens rares (jubeii, polylrose,
mks_zedd, downloads, Cluth) que l'IDF capte. La revue humaine du dry-run est le
filet sémantique — d'où le dry-run par défaut.

Usage :
    python3 scripts/dedupe_mental_state.py                 # dry-run (liste)
    python3 scripts/dedupe_mental_state.py --apply          # applique
    python3 scripts/dedupe_mental_state.py --desire-threshold 0.5 --thought-threshold 0.45
    DB_PATH=/chemin/wally.db python3 scripts/dedupe_mental_state.py --apply

Catégories traitées : DESIRE (fusion), THOUGHT (élagage). Pseudo-souvenirs :
liste curée `PSEUDO_MEMORY_IDS`. Cible par défaut : user `wally:self`.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field

# Mots vides FR/EN courts (aligné sur bot.intelligence.memory.facts).
_STOPWORDS: frozenset[str] = frozenset(
    {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que",
     "qui", "est", "sur", "pour", "dans", "par", "pas", "ce", "ça", "il",
     "the", "and", "for", "with", "this", "that", "are", "was"}
)

# Pseudo-souvenirs CONFIRMÉS faux (revue manuelle des données, 2026-06-27).
# Marqués `needs_review` + confidence baissée. NE PAS étendre par mot-clé :
# polylrose/jubeii1979/mks_zedd sont de vrais users avec des faits légitimes.
PSEUDO_MEMORY_IDS: dict[int, str] = {
    484: "jubeii1979 plays Apex Legends — jubeii joue à Darktide ; c'est mks_zedd qui joue Apex",
    575: "polylrose dislikes Six seven car anglais — hallucination confirmée par Wally (cf #1014)",
}


# --------------------------------------------------------------------------- #
# Fonctions pures — tokenisation, IDF, similarité, clustering
# --------------------------------------------------------------------------- #

def _tokens(text: str) -> set[str]:
    """Sac de tokens normalisés : lower, sans ponctuation, sans stopwords,
    longueur ≥ 3. Conserve les lettres accentuées (unicode word chars)."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return {
        t for t in cleaned.split()
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _idf(docs: list[set[str]]) -> dict[str, float]:
    """IDF lissé : log(N / (1 + df(t))). Token rare → poids élevé."""
    n = len(docs)
    df: dict[str, int] = {}
    for d in docs:
        for t in d:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(n / (1 + c)) + 1.0 for t, c in df.items()}


def _weighted_jaccard(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """Jaccard pondéré IDF : Σ idf[t∈a∩b] / Σ idf[t∈a∪b]. 0 si union vide."""
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    num = sum(idf.get(t, 1.0) for t in inter)
    den = sum(idf.get(t, 1.0) for t in union)
    return num / den if den else 0.0


def cluster(
    items: dict[int, set[str]], threshold: float, idf: dict[str, float]
) -> list[list[int]]:
    """Regroupe les clés de `items` par union-find : deux éléments fusionnent si
    leur similarité pondérée ≥ `threshold`. Retourne une liste de grappes (listes
    de clés). Comparaison O(n²) — suffisant pour quelques milliers de faits."""
    keys = list(items)
    parent = {k: k for k in keys}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            ki, kj = keys[i], keys[j]
            if _weighted_jaccard(items[ki], items[kj], idf) >= threshold:
                union(ki, kj)

    groups: dict[int, list[int]] = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return list(groups.values())


@dataclass
class Fact:
    id: int
    content: str
    last_seen_at: str
    support_count: int = 1
    tokens: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = _tokens(self.content)


@dataclass
class Cluster:
    survivor: Fact
    losers: list[Fact]
    merged_support: int


def plan_merges(facts: list[Fact], threshold: float) -> list[Cluster]:
    """Construit les grappes et choisit, pour chacune, le survivant (le plus
    récent par `last_seen_at`, départage par `id`) ; cumule `support_count`."""
    by_id = {f.id: f for f in facts}
    idf = _idf([f.tokens for f in facts])
    groups = cluster({f.id: f.tokens for f in facts}, threshold, idf)
    out: list[Cluster] = []
    for grp in groups:
        members = [by_id[k] for k in grp]
        survivor = max(members, key=lambda f: (f.last_seen_at, f.id))
        losers = [f for f in members if f.id != survivor.id]
        merged = sum(f.support_count for f in members)
        out.append(Cluster(survivor=survivor, losers=losers, merged_support=merged))
    return out


# --------------------------------------------------------------------------- #
# Couche DB (sqlite3 sync)
# --------------------------------------------------------------------------- #

def load_facts(
    conn: sqlite3.Connection, category: str, user_id: str, status: str
) -> list[Fact]:
    rows = conn.execute(
        """SELECT id, content, last_seen_at, support_count FROM atomic_facts
           WHERE user_id = ? AND category = ? AND status = ?""",
        (user_id, category, status),
    ).fetchall()
    return [
        Fact(id=r[0], content=r[1] or "", last_seen_at=r[2] or "",
             support_count=r[3] if r[3] is not None else 1)
        for r in rows
    ]


def apply_merges(conn: sqlite3.Connection, clusters: list[Cluster]) -> int:
    """Archive les perdants et cumule le support sur le survivant. Retourne le
    nombre de faits archivés."""
    archived = 0
    for c in clusters:
        if not c.losers:
            continue
        conn.execute(
            "UPDATE atomic_facts SET support_count = ? WHERE id = ?",
            (c.merged_support, c.survivor.id),
        )
        ids = [f.id for f in c.losers]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE atomic_facts SET status = 'archived' WHERE id IN ({placeholders})",
            ids,
        )
        archived += len(ids)
    return archived


def apply_pseudo(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Marque les pseudo-souvenirs : status='needs_review', confidence ≤ 0.3.
    Ne touche que les faits encore `active` (idempotent)."""
    touched = 0
    for fid in ids:
        cur = conn.execute(
            """UPDATE atomic_facts
               SET status = 'needs_review', confidence = MIN(confidence, 0.3)
               WHERE id = ? AND status = 'active'""",
            (fid,),
        )
        touched += cur.rowcount
    return touched


# --------------------------------------------------------------------------- #
# Rapport & CLI
# --------------------------------------------------------------------------- #

def _print_clusters(label: str, clusters: list[Cluster]) -> int:
    merges = [c for c in clusters if c.losers]
    total_archived = sum(len(c.losers) for c in merges)
    print(f"\n=== {label} : {len(merges)} grappes, {total_archived} faits à archiver ===")
    for c in sorted(merges, key=lambda x: len(x.losers), reverse=True):
        print(f"\n  ► garde #{c.survivor.id} [{c.survivor.last_seen_at[:16]}] "
              f"(support → {c.merged_support})")
        print(f"      {_oneline(c.survivor.content)}")
        for f in c.losers:
            print(f"    ✗ archive #{f.id} [{f.last_seen_at[:16]}]  {_oneline(f.content)}")
    return total_archived


def _oneline(s: str, n: int = 90) -> str:
    return " ".join((s or "").split())[:n]


def main() -> int:
    parser = argparse.ArgumentParser(description="Nettoyage de la dette mentale (Phase 5)")
    parser.add_argument("--db", default=os.getenv("DB_PATH", "data/wally.db"))
    parser.add_argument("--apply", action="store_true", help="applique (sinon dry-run)")
    parser.add_argument("--user", default="wally:self")
    # Seuils calibrés sur les données réelles (2026-06-27, dry-run inspecté) :
    # 0.30 désirs → grappes nettes (jubeii ×9, mks_zedd ×6…), 0 fusion abusive.
    # 0.25 pensées → ruminations consécutives (test-emoji ×10…), quelques
    # regroupements sur le cadre stéréotypé (réversible, à revoir au dry-run).
    parser.add_argument("--desire-threshold", type=float, default=0.30)
    parser.add_argument("--thought-threshold", type=float, default=0.25)
    parser.add_argument("--skip-desires", action="store_true")
    parser.add_argument("--skip-thoughts", action="store_true")
    parser.add_argument("--skip-pseudo", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"DB introuvable : {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    print(f"DB : {args.db}  |  user : {args.user}  |  mode : "
          f"{'APPLY' if args.apply else 'DRY-RUN'}")

    desire_clusters: list[Cluster] = []
    thought_clusters: list[Cluster] = []
    pseudo_ids: list[int] = []

    if not args.skip_desires:
        facts = load_facts(conn, "DESIRE", args.user, "active")
        desire_clusters = plan_merges(facts, args.desire_threshold)
        _print_clusters(f"DESIRE (seuil {args.desire_threshold})", desire_clusters)

    if not args.skip_thoughts:
        facts = load_facts(conn, "THOUGHT", args.user, "active")
        thought_clusters = plan_merges(facts, args.thought_threshold)
        _print_clusters(f"THOUGHT (seuil {args.thought_threshold})", thought_clusters)

    if not args.skip_pseudo:
        pseudo_ids = list(PSEUDO_MEMORY_IDS)
        print(f"\n=== PSEUDO-SOUVENIRS curés : {len(pseudo_ids)} ===")
        for fid, reason in PSEUDO_MEMORY_IDS.items():
            row = conn.execute(
                "SELECT status, content FROM atomic_facts WHERE id = ?", (fid,)
            ).fetchone()
            if row is None:
                print(f"  #{fid} (introuvable)")
            else:
                print(f"  #{fid} [{row[0]}] {_oneline(row[1])}\n      → {reason}")

    if not args.apply:
        print("\n[DRY-RUN] Aucune écriture. Relancer avec --apply pour appliquer.")
        conn.close()
        return 0

    n_des = apply_merges(conn, desire_clusters)
    n_tho = apply_merges(conn, thought_clusters)
    n_pseudo = apply_pseudo(conn, pseudo_ids)
    conn.commit()
    conn.close()
    print(f"\n✅ Appliqué : {n_des} désirs archivés, {n_tho} pensées archivées, "
          f"{n_pseudo} pseudo-souvenirs marqués needs_review. (réversible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
