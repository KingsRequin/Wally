"""Social graph API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter()


def _get_graph(request: Request):
    """Return GraphService from app state, or None if unavailable."""
    state = request.app.state.wally
    graph = getattr(state, "graph", None)
    if graph is None or not graph.ready:
        return None
    return graph


@router.get("/social-graph/data")
async def get_graph_data(request: Request):
    """Return nodes and edges for the social graph visualization."""
    graph = _get_graph(request)
    if graph is None:
        return {"nodes": [], "edges": []}
    try:
        driver = graph._graphiti._driver
        gid = graph._sanitize_group_id(graph._config.graphiti.group_id)
        async with driver.session() as session:
            # Get Entity nodes
            result = await session.run(
                "MATCH (n:Entity) "
                "WHERE n.group_id = $gid "
                "RETURN n.uuid AS id, n.name AS name, n.summary AS summary, "
                "       labels(n) AS labels "
                "ORDER BY n.name "
                "LIMIT 200",
                {"gid": gid},
            )
            nodes = [dict(record) async for record in result]

            # Get active relationships (not invalidated)
            result = await session.run(
                "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                "WHERE a.group_id = $gid AND r.invalid_at IS NULL "
                "RETURN a.uuid AS source, b.uuid AS target, "
                "       r.name AS type, r.fact AS fact, "
                "       a.name AS source_name, b.name AS target_name "
                "ORDER BY r.created_at DESC "
                "LIMIT 500",
                {"gid": gid},
            )
            edges = [dict(record) async for record in result]

        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        logger.warning("Social graph query failed: {e}", e=exc)
        return {"nodes": [], "edges": []}


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
        driver = graph._graphiti._driver
        gid = graph._sanitize_group_id(graph._config.graphiti.group_id)
        async with driver.session() as session:
            result = await session.run(
                "MATCH (c:Community)-[:HAS_MEMBER]->(e:Entity) "
                "WHERE c.group_id = $gid "
                "RETURN c.uuid AS id, c.name AS name, c.summary AS summary, "
                "       collect(e.name) AS members "
                "LIMIT 50",
                {"gid": gid},
            )
            communities = [dict(record) async for record in result]
        return {"communities": communities}
    except Exception as exc:
        logger.warning("Communities query failed: {e}", e=exc)
        return {"communities": []}
