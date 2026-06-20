"""Social graph API endpoints."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter()
public_router = APIRouter()

# In-memory TTL cache: group_id -> (timestamp, data)
_graph_cache: dict[str, tuple[float, dict]] = {}
_GRAPH_CACHE_TTL = 60.0  # seconds


def _get_graph(request: Request):
    """Return GraphService from app state, or None if unavailable."""
    state = request.app.state.wally
    graph = getattr(state, "graph", None)
    if graph is None or not graph.ready:
        return None
    return graph


async def _graph_data(request: Request) -> dict:
    """Shared logic for social graph data."""
    graph = _get_graph(request)
    if graph is None:
        return {"nodes": [], "edges": []}
    try:
        driver = graph._graphiti.driver
        gid = graph._sanitize_group_id(graph._config.graphiti.group_id)

        # Serve from cache if fresh
        now = time.time()
        if gid in _graph_cache:
            ts, cached = _graph_cache[gid]
            if now - ts < _GRAPH_CACHE_TTL:
                return cached

        # Filter entities to keep only likely human persons.
        # Cypher handles the structural/syntactic cases; Python post-filters
        # semantic junk (phrases, articles, known non-person names).
        # Only include nodes that have at least one RELATES_TO edge (no isolated nodes).
        result = await driver.execute_query(
            "MATCH (n:Entity) "
            "WHERE n.group_id = $gid "
            # ── exclude isolated nodes (no edges) ──────────────────────
            "  AND (n)-[:RELATES_TO]-() "
            # ── structural junk ──────────────────────────────────────────
            "  AND n.name <> 'unknown' "
            "  AND n.name <> 'system' "
            "  AND n.name <> 'je' "
            "  AND NOT n.name CONTAINS '<@' "
            # ── commas = phrase-like descriptions ──────────────────────
            "  AND NOT n.name CONTAINS ',' "
            # ── keep names short enough to be a real pseudo/firstname ──
            "  AND size(n.name) <= 40 "
            # ── very long multi-word names are likely sentences ─────────
            "  AND NOT (size(n.name) > 28 AND n.name CONTAINS ' ') "
            "RETURN n.uuid AS id, n.name AS name, n.summary AS summary, "
            "       labels(n) AS labels "
            "ORDER BY n.name "
            "LIMIT 200",
            params={"gid": gid},
        )
        raw_nodes = [dict(record) for record in result.records]

        # Python post-filter: remove names that look like French noun-phrases
        # or common non-person words that slipped through the Cypher filter.
        import re as _re
        _ARTICLE_PREFIX = (
            "le ", "la ", "les ", "l'", "de ", "du ", "des ", "d'",
            "un ", "une ", "mon ", "ton ", "son ", "nos ", "vos ",
            "en ", "au ", "aux ", "par ", "pour ", "avec ", "sur ",
            "ce ", "cet ", "cette ", "ces ",
        )
        _KNOWN_NON_PERSONS = {
            # Platforms / services
            "internet", "discord", "twitch", "youtube", "reddit",
            "steam", "epic", "minecraft", "valorant", "fortnite",
            "lol", "league", "overwatch", "apex", "dota",
            "spotify", "netflix", "twitch", "github", "google",
            "twitter", "instagram", "tiktok", "facebook",
            # Technical
            "social tracker", "social_tracker", "bot", "wally",
            # Common French nouns that pass through
            "serveur", "canal", "salon", "message", "jeu", "jeux",
            "chat", "chats", "groupe", "communauté", "équipe",
            "ami", "amis", "amie", "amies", "gens", "monde",
            "truc", "trucs", "chose", "choses", "moment", "moments",
            "fois", "heure", "heures", "jour", "jours", "semaine",
            "matin", "soir", "nuit", "midi", "temps",
        }
        _LATIN_ONLY = _re.compile(r"^[a-zàâäéèêëïîôùûüçœæ '\-]+$")
        _SENTENCE_PUNCT = set("!?.,;:()[]{}\"")

        def _is_person_like(name: str) -> bool:
            low = name.lower()
            if low in _KNOWN_NON_PERSONS:
                return False
            # starts with a French determiner/article/preposition
            if any(low.startswith(p) for p in _ARTICLE_PREFIX):
                return False
            # pure ASCII snake_case (underscore in the middle) = technical identifier
            # Trailing underscore (e.g. "elhya_") = Discord username style → keep
            if "_" in name and not name.endswith("_") and not name.startswith("_") and _re.fullmatch(r"[a-z][a-z0-9_]+", name):
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
            # purely lowercase regular Latin text + spaces → likely a phrase/topic
            # NOT applied to names with emoji or non-Latin Unicode (decorated Discord names)
            if name == low and " " in name and _LATIN_ONLY.match(name):
                return False
            # single lowercase Latin word (no digits, no uppercase) shorter than 3 chars
            if name == low and _re.fullmatch(r"[a-zàâäéèêëïîôùûüçœæ]+", name) and len(name) < 3:
                return False
            return True

        # Filter non-person nodes
        filtered_nodes = [n for n in raw_nodes if _is_person_like(n["name"])]

        # Déduplication case-insensitive : si deux nœuds ont le même nom (casse différente),
        # on garde celui qui apparaît en premier (ORDER BY name → alphabétique).
        # Les arêtes pointant vers le doublon sont remappées vers le nœud canonique.
        canonical_by_low: dict[str, dict] = {}  # name.lower() -> node retenu
        uuid_remap: dict[str, str] = {}          # uuid_doublon -> uuid_canonique
        for n in filtered_nodes:
            low = n["name"].lower()
            if low not in canonical_by_low:
                canonical_by_low[low] = n
            else:
                # Doublon : remappe son uuid vers le nœud canonique
                uuid_remap[n["id"]] = canonical_by_low[low]["id"]

        nodes = list(canonical_by_low.values())
        node_ids = {n["id"] for n in nodes}

        # Résolution Discord ID → display name.
        # Les nouveaux signaux sociaux utilisent les snowflakes Discord comme
        # nom d'entité (e.g. "610550333042589752"). On les résout via memory_users.
        import re as _re_id
        _DISCORD_ID_RE = _re_id.compile(r"^\d{17,19}$")
        db = getattr(request.app.state.wally, "db", None)
        id_to_display: dict[str, str] = {}
        if db is not None:
            raw_ids = [n["name"] for n in nodes if _DISCORD_ID_RE.match(n["name"])]
            if raw_ids:
                try:
                    placeholders = ",".join("?" * len(raw_ids))
                    rows = await db.fetch_all(
                        f"SELECT user_id, username FROM memory_users "
                        f"WHERE user_id IN ({placeholders})",
                        tuple(f"discord:{rid}" for rid in raw_ids),
                    )
                    for row in rows:
                        raw = row["user_id"].removeprefix("discord:")
                        name = row["username"] or raw
                        id_to_display[raw] = name
                except Exception as _exc:
                    logger.warning("ID resolution query failed: {e}", e=_exc)

        # Applique la résolution aux nœuds (ajoute discord_id si résolu)
        for n in nodes:
            if _DISCORD_ID_RE.match(n["name"]):
                resolved = id_to_display.get(n["name"], n["name"])
                n["discord_id"] = n["name"]
                n["name"] = resolved

        # Récupère toutes les arêtes (valides ET invalidées) pour ne rater
        # aucune connexion sociale réelle. Les invalidations Graphiti reflètent
        # des déduplication/contradictions factuelles, pas l'absence d'interaction.
        # On garde la plus récente arête par paire (non-orientée) pour éviter
        # les doublons, en préférant les arêtes valides (invalid_at IS NULL).
        result = await driver.execute_query(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            "WHERE a.group_id = $gid "
            "  AND a.name <> 'unknown' AND b.name <> 'unknown' "
            "  AND a.name <> 'system' AND b.name <> 'system' "
            "RETURN a.uuid AS source, b.uuid AS target, "
            "       r.name AS type, r.fact AS fact, "
            "       a.name AS source_name, b.name AS target_name, "
            "       r.invalid_at IS NULL AS is_valid "
            "ORDER BY r.invalid_at IS NULL DESC, r.created_at DESC "
            "LIMIT 1000",
            params={"gid": gid},
        )
        # Remappe les UUIDs doublons, puis filtre les arêtes dont les deux extrémités
        # existent dans les nœuds retenus (après déduplication).
        def _remap(uid: str) -> str:
            return uuid_remap.get(uid, uid)

        raw_edges = [
            {**dict(record),
             "source": _remap(record["source"]),
             "target": _remap(record["target"])}
            for record in result.records
            if _remap(record["source"]) in node_ids
            and _remap(record["target"]) in node_ids
        ]

        # Dédupliquer par paire non-orientée {min_id, max_id} et agréger les facts + weight.
        # Les arêtes valides (is_valid=True) arrivent en premier grâce au ORDER BY,
        # donc la première occurrence pour chaque paire est la plus pertinente.
        from collections import defaultdict
        seen_pairs: set[frozenset] = set()
        pair_data: dict[tuple, dict] = defaultdict(lambda: {"facts": [], "types": set()})
        for e in raw_edges:
            pair_key = frozenset({e["source"], e["target"]})
            canonical = (min(e["source"], e["target"]), max(e["source"], e["target"]))
            seen_pairs.add(pair_key)
            key = (e["source"], e["target"])
            pair_data[key]["facts"].append(e["fact"] or "")
            pair_data[key]["types"].add(e["type"] or "")
            pair_data[key]["source_name"] = e["source_name"]
            pair_data[key]["target_name"] = e["target_name"]

        # Fusionner les deux directions (a→b et b→a) en une seule arête
        merged: dict[frozenset, dict] = {}
        for (src, tgt), data in pair_data.items():
            pk = frozenset({src, tgt})
            if pk not in merged:
                merged[pk] = {
                    "source": src, "target": tgt,
                    "facts": [], "types": set(),
                    "source_name": data["source_name"],
                    "target_name": data["target_name"],
                }
            merged[pk]["facts"].extend(data["facts"])
            merged[pk]["types"].update(data["types"])

        def _resolve_edge_name(raw: str) -> str:
            if _DISCORD_ID_RE.match(raw):
                return id_to_display.get(raw, raw)
            return raw

        # Exclure les auto-boucles (source == target)
        edges = [
            {
                "source": d["source"],
                "target": d["target"],
                "weight": len(d["facts"]),
                "facts": [f for f in d["facts"] if f],
                "types": list(d["types"]),
                "source_name": _resolve_edge_name(d["source_name"]),
                "target_name": _resolve_edge_name(d["target_name"]),
            }
            for d in merged.values()
            if d["source"] != d["target"]
        ]

        data = {"nodes": nodes, "edges": edges}
        _graph_cache[gid] = (time.time(), data)
        return data
    except Exception as exc:
        logger.warning("Social graph query failed: {e}", e=exc)
        return {"nodes": [], "edges": []}


@public_router.get("/social-graph/data")
async def get_graph_data_public(request: Request):
    """Return nodes and edges for the social graph visualization (public)."""
    return await _graph_data(request)


@router.get("/social-graph/data")
async def get_graph_data(request: Request):
    """Return nodes and edges for the social graph visualization (admin)."""
    return await _graph_data(request)


@router.get("/social-graph/affinity/{user_a}/{user_b}")
async def get_affinity(user_a: str, user_b: str, request: Request):
    """Get affinity score between two users."""
    graph = _get_graph(request)
    if graph is None:
        return {"score": 0.0}
    try:
        score = await graph.get_affinity(user_a, user_b)
        return {"score": round(score, 2)}
    except Exception as exc:
        logger.warning("Affinity query failed: {e}", e=exc)
        return {"score": 0.0}


@router.get("/social-graph/communities")
async def get_communities(request: Request):
    """Return community nodes for the graph."""
    graph = _get_graph(request)
    if graph is None:
        return {"communities": []}
    try:
        driver = graph._graphiti.driver
        gid = graph._sanitize_group_id(graph._config.graphiti.group_id)

        result = await driver.execute_query(
            "MATCH (c:Community)-[:HAS_MEMBER]->(e:Entity) "
            "WHERE c.group_id = $gid "
            "RETURN c.uuid AS id, c.name AS name, c.summary AS summary, "
            "       collect(e.name) AS members "
            "LIMIT 50",
            params={"gid": gid},
        )
        communities = [dict(record) for record in result.records]
        return {"communities": communities}
    except Exception as exc:
        logger.warning("Communities query failed: {e}", e=exc)
        return {"communities": []}
