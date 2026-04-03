"""Social graph API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter()
public_router = APIRouter()


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

        # Filter out junk entities: unknown, raw messages, unresolved mentions
        result = await driver.execute_query(
            "MATCH (n:Entity) "
            "WHERE n.group_id = $gid "
            "  AND n.name <> 'unknown' "
            "  AND n.name <> 'system' "
            "  AND n.name <> 'je' "
            "  AND NOT n.name CONTAINS '<@' "
            "  AND size(n.name) <= 50 "
            "RETURN n.uuid AS id, n.name AS name, n.summary AS summary, "
            "       labels(n) AS labels "
            "ORDER BY n.name "
            "LIMIT 200",
            params={"gid": gid},
        )
        nodes = [dict(record) for record in result.records]
        node_ids = {n["id"] for n in nodes}

        result = await driver.execute_query(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
            "WHERE a.group_id = $gid AND r.invalid_at IS NULL "
            "  AND a.name <> 'unknown' AND b.name <> 'unknown' "
            "  AND a.name <> 'system' AND b.name <> 'system' "
            "RETURN a.uuid AS source, b.uuid AS target, "
            "       r.name AS type, r.fact AS fact, "
            "       a.name AS source_name, b.name AS target_name "
            "ORDER BY r.created_at DESC "
            "LIMIT 500",
            params={"gid": gid},
        )
        # Only keep edges where both ends exist in filtered nodes
        raw_edges = [
            dict(record) for record in result.records
            if record["source"] in node_ids and record["target"] in node_ids
        ]

        # Dédupliquer par paire (source, target) et agréger les facts + weight
        from collections import defaultdict
        pair_data: dict[tuple, dict] = defaultdict(lambda: {"facts": [], "types": set()})
        for e in raw_edges:
            key = (e["source"], e["target"])
            pair_data[key]["facts"].append(e["fact"] or "")
            pair_data[key]["types"].add(e["type"] or "")
            # Conserver les noms pour la lisibilité côté client
            pair_data[key]["source_name"] = e["source_name"]
            pair_data[key]["target_name"] = e["target_name"]

        edges = [
            {
                "source": src,
                "target": tgt,
                "weight": len(data["facts"]),
                "facts": [f for f in data["facts"] if f],
                "types": list(data["types"]),
                "source_name": data["source_name"],
                "target_name": data["target_name"],
            }
            for (src, tgt), data in pair_data.items()
        ]

        return {"nodes": nodes, "edges": edges}
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
