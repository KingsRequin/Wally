"""GraphService — Graphiti facade for Wally's knowledge graph."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from bot.config import Config

# Lazy imports to avoid crash when graphiti not installed
_graphiti_available = False
try:
    from graphiti_core import Graphiti
    from graphiti_core.llm_client import LLMConfig, OpenAIClient
    from graphiti_core.nodes import EpisodeType
    _graphiti_available = True
except ImportError:
    pass


class GraphService:
    """Facade over Graphiti for knowledge graph operations."""

    def __init__(self, config: "Config"):
        self._config = config
        self._graphiti: Any | None = None
        self._ready = False

    async def initialize(self) -> bool:
        """Connect to Neo4j and build indices. Returns True if successful."""
        gc = self._config.graphiti
        if not gc.enabled or not _graphiti_available:
            logger.info("GraphService disabled (enabled={e}, available={a})",
                        e=gc.enabled, a=_graphiti_available)
            return False
        try:
            llm_client = OpenAIClient(config=LLMConfig(
                model=gc.llm_model,
                small_model=gc.llm_model,
            ))
            self._graphiti = Graphiti(
                uri=gc.neo4j_uri,
                user=gc.neo4j_user,
                password=gc.neo4j_password,
                llm_client=llm_client,
            )
            await self._graphiti.build_indices_and_constraints()
            self._ready = True
            logger.info("GraphService connected to Neo4j at {uri}", uri=gc.neo4j_uri)
            return True
        except Exception as exc:
            logger.warning("GraphService init failed: {e}", e=exc)
            self._graphiti = None
            self._ready = False
            return False

    @property
    def ready(self) -> bool:
        return self._ready and self._graphiti is not None

    async def add_episode(
        self,
        content: str,
        author: str,
        source: str = "discord",
        group_id: str | None = None,
        update_communities: bool = False,
    ) -> dict | None:
        """Ingest a message into the knowledge graph.

        Returns extracted entities/edges summary or None on failure.
        """
        if not self.ready:
            return None
        try:
            gid = group_id or self._config.graphiti.group_id
            result = await self._graphiti.add_episode(
                name=f"{source} message",
                episode_body=f"{author}: {content}",
                source_description=f"{source} chat",
                source=EpisodeType.message,
                reference_time=datetime.now(timezone.utc),
                group_id=gid,
                update_communities=update_communities,
            )
            entities = [n.name for n in result.nodes] if result.nodes else []
            edges = [e.fact for e in result.edges] if result.edges else []
            logger.debug(
                "Graph episode added: {n} entities, {e} edges",
                n=len(entities), e=len(edges),
            )
            return {"entities": entities, "edges": edges}
        except Exception as exc:
            logger.warning("Graph add_episode failed: {e}", e=exc)
            return None

    async def search(
        self,
        query: str,
        group_id: str | None = None,
        num_results: int = 10,
    ) -> list[dict]:
        """Search the knowledge graph. Returns list of fact dicts."""
        if not self.ready:
            return []
        try:
            gid = group_id or self._config.graphiti.group_id
            edges = await self._graphiti.search(
                query=query,
                group_ids=[gid],
                num_results=num_results,
            )
            return [
                {
                    "fact": edge.fact,
                    "name": edge.name,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                    "invalid_at": str(edge.invalid_at) if edge.invalid_at else None,
                }
                for edge in edges
            ]
        except Exception as exc:
            logger.warning("Graph search failed: {e}", e=exc)
            return []

    async def get_affinity(self, user_a: str, user_b: str, group_id: str | None = None) -> float:
        """Calculate affinity score between two users based on graph edges."""
        if not self.ready:
            return 0.0
        try:
            gid = group_id or self._config.graphiti.group_id
            edges = await self._graphiti.search(
                query=f"{user_a} {user_b}",
                group_ids=[gid],
                num_results=20,
            )
            weights = self._config.graphiti.affinity_weights
            score = 0.0
            for edge in edges:
                fact = (edge.fact or "").lower()
                if "vocal" in fact:
                    score += weights.get("voice", 3.0)
                elif "répondu" in fact:
                    score += weights.get("reply", 2.0)
                elif "mentionné" in fact:
                    score += weights.get("mention", 1.5)
                elif "réagi" in fact:
                    score += weights.get("reaction", 1.0)
                elif "thread" in fact:
                    score += weights.get("thread", 1.0)
                elif "joué" in fact:
                    score += weights.get("game", 2.5)
            return score
        except Exception as exc:
            logger.warning("Affinity calculation failed: {e}", e=exc)
            return 0.0

    async def close(self) -> None:
        """Shutdown Graphiti and close Neo4j connection."""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                pass
            self._graphiti = None
            self._ready = False
