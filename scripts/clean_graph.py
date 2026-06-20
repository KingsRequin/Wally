#!/usr/bin/env python3
"""Nettoyage du graphe social Neo4j — doublons et entités non-humaines.

Usage:
    python scripts/clean_graph.py [--dry-run] [--uri bolt://neo4j:7687]
                                   [--user neo4j] [--password changeme]
                                   [--group-id discord-default]

Actions effectuées :
  1. Affiche le nombre total de nœuds Entity dans le groupe.
  2. Détecte les doublons case-insensitive (même nom, casse différente).
     → En mode réel : fusionne les arêtes sur le nœud canonique et supprime le doublon.
  3. Détecte les nœuds non-humains selon les mêmes règles que le dashboard.
     → En mode réel : supprime ces nœuds et leurs arêtes.
  4. Affiche un résumé des opérations.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from typing import Any

try:
    from neo4j import GraphDatabase
except ImportError:
    print("Erreur : neo4j-driver non installé. pip install neo4j", file=sys.stderr)
    sys.exit(1)


# ── Même logique de filtrage que routes/graph.py ─────────────────────────────

_ARTICLE_PREFIX = (
    "le ", "la ", "les ", "l'", "de ", "du ", "des ", "d'",
    "un ", "une ", "mon ", "ton ", "son ", "nos ", "vos ",
    "en ", "au ", "aux ", "par ", "pour ", "avec ", "sur ",
    "ce ", "cet ", "cette ", "ces ",
)
_KNOWN_NON_PERSONS = {
    "internet", "discord", "twitch", "youtube", "reddit",
    "steam", "epic", "minecraft", "valorant", "fortnite",
    "lol", "league", "overwatch", "apex", "dota",
    "spotify", "netflix", "github", "google",
    "twitter", "instagram", "tiktok", "facebook",
    "social tracker", "social_tracker", "bot", "wally",
    "serveur", "canal", "salon", "message", "jeu", "jeux",
    "chat", "chats", "groupe", "communauté", "équipe",
    "ami", "amis", "amie", "amies", "gens", "monde",
    "truc", "trucs", "chose", "choses", "moment", "moments",
    "fois", "heure", "heures", "jour", "jours", "semaine",
    "matin", "soir", "nuit", "midi", "temps",
}
_LATIN_ONLY = re.compile(r"^[a-zàâäéèêëïîôùûüçœæ '\-]+$")
_SENTENCE_PUNCT = set("!?.,;:()[]{}\"")


def _is_person_like(name: str) -> bool:
    low = name.lower()
    if low in _KNOWN_NON_PERSONS:
        return False
    if any(low.startswith(p) for p in _ARTICLE_PREFIX):
        return False
    if "_" in name and not name.endswith("_") and not name.startswith("_") and re.fullmatch(r"[a-z][a-z0-9_]+", name):
        return False
    # sentence punctuation → definitely not a username
    if any(c in name for c in _SENTENCE_PUNCT):
        return False
    # French apostrophe contractions (c'est, j'ai, …) = sentence fragment
    if ("'" in name or "\u2019" in name) and " " in name:
        return False
    # 4+ words → sentence, not a name
    if len(name.split()) >= 4:
        return False
    if name == low and " " in name and _LATIN_ONLY.match(name):
        return False
    if name == low and re.fullmatch(r"[a-zàâäéèêëïîôùûüçœæ]+", name) and len(name) < 3:
        return False
    # Additional Cypher-level checks reproduced here
    if name in ("unknown", "system", "je"):
        return False
    if "<@" in name:
        return False
    if "," in name:
        return False
    if len(name) > 40:
        return False
    if len(name) > 28 and " " in name:
        return False
    return True


# ── Neo4j helpers ─────────────────────────────────────────────────────────────

def fetch_all_entities(session, gid: str) -> list[dict[str, Any]]:
    result = session.run(
        "MATCH (n:Entity) WHERE n.group_id = $gid "
        "RETURN n.uuid AS id, n.name AS name",
        gid=gid,
    )
    return [{"id": r["id"], "name": r["name"]} for r in result]


def merge_duplicate(session, keep_id: str, drop_id: str, dry_run: bool) -> int:
    """Redirige toutes les arêtes de drop_id vers keep_id, puis supprime drop_id.

    Returns number of relationships remapped.
    """
    if dry_run:
        result = session.run(
            "MATCH (n:Entity {uuid: $drop_id})-[r]-() RETURN count(r) AS cnt",
            drop_id=drop_id,
        )
        return result.single()["cnt"]

    # Remappe les arêtes sortantes
    session.run(
        "MATCH (drop:Entity {uuid: $drop_id})-[r:RELATES_TO]->(b:Entity) "
        "MATCH (keep:Entity {uuid: $keep_id}) "
        "WHERE drop <> keep AND b <> keep "
        "MERGE (keep)-[r2:RELATES_TO]->(b) "
        "ON CREATE SET r2 = properties(r) "
        "DELETE r",
        drop_id=drop_id, keep_id=keep_id,
    )
    # Remappe les arêtes entrantes
    session.run(
        "MATCH (a:Entity)-[r:RELATES_TO]->(drop:Entity {uuid: $drop_id}) "
        "MATCH (keep:Entity {uuid: $keep_id}) "
        "WHERE a <> keep AND drop <> keep "
        "MERGE (a)-[r2:RELATES_TO]->(keep) "
        "ON CREATE SET r2 = properties(r) "
        "DELETE r",
        drop_id=drop_id, keep_id=keep_id,
    )
    # Supprime le nœud doublon (et ses éventuelles arêtes résiduelles avec keep)
    result = session.run(
        "MATCH (n:Entity {uuid: $drop_id}) "
        "OPTIONAL MATCH (n)-[r]-() DELETE r, n RETURN count(n) AS cnt",
        drop_id=drop_id,
    )
    return result.single()["cnt"]


def delete_node(session, node_id: str, dry_run: bool) -> None:
    """Supprime un nœud Entity et toutes ses relations."""
    if dry_run:
        return
    session.run(
        "MATCH (n:Entity {uuid: $nid}) OPTIONAL MATCH (n)-[r]-() DELETE r, n",
        nid=node_id,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run(uri: str, user: str, password: str, gid: str, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n=== clean_graph.py [{mode}] — group_id={gid} ===\n")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            entities = fetch_all_entities(session, gid)
            print(f"Nœuds Entity dans le groupe : {len(entities)}")

            # ── 1. Doublons case-insensitive ──────────────────────────────────
            by_lower: dict[str, list[dict]] = defaultdict(list)
            for e in entities:
                by_lower[e["name"].lower()].append(e)

            duplicates = {k: v for k, v in by_lower.items() if len(v) > 1}
            print(f"\n[1/2] Doublons détectés : {len(duplicates)} groupes\n")

            merged_total = 0
            for low, group in sorted(duplicates.items()):
                # Nœud canonique = premier dans l'ordre alphabétique original
                group_sorted = sorted(group, key=lambda n: n["name"])
                keep = group_sorted[0]
                drops = group_sorted[1:]
                names = [n["name"] for n in group_sorted]
                print(f"  → Fusion '{keep['name']}' ← {[d['name'] for d in drops]}")
                for drop in drops:
                    cnt = merge_duplicate(session, keep["id"], drop["id"], dry_run)
                    merged_total += 1
                    print(f"     {'[DRY]' if dry_run else '[OK]'} suppression {drop['name']} "
                          f"({cnt} relation(s) remappée(s))")

            print(f"\n  Total fusionnés : {merged_total} nœuds doublons")

            # Recharge les entités après fusion
            entities = fetch_all_entities(session, gid)

            # ── 2. Entités non-humaines ───────────────────────────────────────
            non_persons = [e for e in entities if not _is_person_like(e["name"])]
            print(f"\n[2/2] Entités non-humaines détectées : {len(non_persons)}\n")

            for e in non_persons:
                print(f"  → Suppression '{e['name']}' (id={e['id'][:8]}…)")
                delete_node(session, e["id"], dry_run)
                print(f"     {'[DRY]' if dry_run else '[OK]'}")

            # ── Résumé ────────────────────────────────────────────────────────
            print(f"\n{'='*50}")
            print(f"Résumé [{mode}]")
            print(f"  Doublons fusionnés  : {merged_total}")
            print(f"  Non-humains supprimés: {len(non_persons)}")
            if dry_run:
                print("\n  ⚠ Aucun changement effectué (--dry-run).")
                print("  Relancer sans --dry-run pour appliquer.")
            else:
                print("\n  ✓ Nettoyage terminé.")
            print()
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nettoie le graphe social Neo4j")
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche les opérations sans les exécuter")
    parser.add_argument("--uri", default="bolt://localhost:7687",
                        help="URI Neo4j (default: bolt://localhost:7687)")
    parser.add_argument("--user", default="neo4j", help="Utilisateur Neo4j")
    parser.add_argument("--password", default="changeme", help="Mot de passe Neo4j")
    parser.add_argument("--group-id", default="discord-default",
                        help="group_id Graphiti (default: discord-default)")
    args = parser.parse_args()
    run(
        uri=args.uri,
        user=args.user,
        password=args.password,
        gid=args.group_id,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
