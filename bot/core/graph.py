"""GraphService — Graphiti facade for Wally's knowledge graph."""
from __future__ import annotations

import re
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

    @staticmethod
    def _sanitize_group_id(group_id: str) -> str:
        """Replace characters not allowed by Graphiti (only alphanumeric, - and _)."""
        return re.sub(r"[^a-zA-Z0-9_-]", "-", group_id)

    # ── Pre-ingestion filters ──

    _DISCORD_SYNTAX_RE = re.compile(
        r"<@[!&]?\d+>"                      # @user / @role mentions
        r"|<#\d+>"                           # #channel mentions
        r"|<:\w+:\d+>"                       # :custom_emoji:
        r"|<a:\w+:\d+>"                      # :animated_emoji:
        r"|<t:\d+(?::[tTdDfFR])?>"          # Discord timestamps
    )
    _EMOJI_ONLY_RE = re.compile(
        r"^[\s"
        r"\U0001f600-\U0001f64f"   # emoticons
        r"\U0001f300-\U0001f5ff"   # symbols & pictographs
        r"\U0001f680-\U0001f6ff"   # transport & map
        r"\U0001f900-\U0001f9ff"   # supplemental symbols
        r"\U0001fa00-\U0001fa6f"   # chess, medical
        r"\U0001fa70-\U0001faff"   # symbols extended-A
        r"\U00002600-\U000026ff"   # misc symbols (☀ ⚡ etc.)
        r"\U00002700-\U000027bf"   # dingbats
        r"\U0000200d"              # zero-width joiner (family emojis)
        r"\U0000fe0f"              # variation selector-16
        r"]+$"
    )
    _MIN_CONTENT_LENGTH = 20  # ignore very short messages

    @classmethod
    def _clean_content(cls, content: str) -> str | None:
        """Clean and validate content before ingestion.

        Returns cleaned content or None if the message should be skipped.
        """
        text = content.strip()
        if len(text) < cls._MIN_CONTENT_LENGTH:
            return None
        # Strip all Discord-specific syntax — they produce garbage entities
        text = cls._DISCORD_SYNTAX_RE.sub("", text)
        text = " ".join(text.split())  # normalize multiple spaces
        if len(text) < cls._MIN_CONTENT_LENGTH:
            return None
        # Skip emoji-only
        if cls._EMOJI_ONLY_RE.match(text):
            return None
        # Skip media/URL-only
        if text.startswith("http") and " " not in text:
            return None
        return text

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
        Skips messages that are too short, emoji-only, or contain only
        unresolved Discord mentions.
        """
        if not self.ready:
            return None

        is_social = source == "social_tracker"
        # Skip unknown authors — they create useless "unknown" entities.
        # Social signals (is_social=True) have no author by design — allow them through.
        if not is_social and (not author or author.lower() == "unknown"):
            return None

        cleaned = self._clean_content(content)
        if cleaned is None:
            return None

        try:
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
            result = await self._graphiti.add_episode(
                name="social signal" if is_social else "discord message",
                episode_body=cleaned if is_social else f"{author}: {cleaned}",
                source_description=(
                    # Social signals: structured person-to-person interactions
                    "Social interaction signal between Discord users. "
                    "ONLY extract human person names (first names or pseudonyms). "
                    "DO NOT create entities for: bots, AI, virtual assistants, objects, "
                    "concepts, places, food, games, websites, or any non-human thing. "
                    "Entity names must be real human usernames or nicknames only."
                ) if is_social else (
                    # Regular messages: also restrict to people only — topics and objects
                    # pollute the social graph with non-person entities.
                    f"Discord conversation in French. Author: {author}. "
                    "ONLY extract human person names (first names, pseudonyms, usernames). "
                    "DO NOT create entities for: objects, food, games, websites, concepts, "
                    "places, or any non-human subject. "
                    "If no human person names are mentioned, extract nothing."
                ),
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
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
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
        """Calculate affinity score between two users using a direct Cypher query.

        Weights are inferred from the fact text (French social signal templates)
        because Graphiti stores free-form fact descriptions, not typed edge enums.
        """
        if not self.ready:
            return 0.0
        try:
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
            result = await self._graphiti.driver.execute_query(
                "MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid}) "
                "WHERE toLower(a.name) = $name_a AND toLower(b.name) = $name_b "
                "  AND r.invalid_at IS NULL "
                "RETURN r.fact AS fact",
                params={"gid": gid, "name_a": user_a.lower(), "name_b": user_b.lower()},
            )
            weights = self._config.graphiti.affinity_weights
            score = 0.0
            for record in result.records:
                fact = (record["fact"] or "").lower()
                if "vocal" in fact:
                    score += weights.get("voice", 3.0)
                elif "joué" in fact or "jeu" in fact:
                    score += weights.get("game", 2.5)
                elif "répondu" in fact:
                    score += weights.get("reply", 2.0)
                elif "mentionné" in fact:
                    score += weights.get("mention", 1.5)
                elif "réagi" in fact or "réaction" in fact:
                    score += weights.get("reaction", 1.0)
                elif "thread" in fact:
                    score += weights.get("thread", 1.0)
                else:
                    score += 1.0
            return round(score, 2)
        except Exception as exc:
            logger.warning("Affinity calculation failed: {e}", e=exc)
            return 0.0

    async def get_social_context(
        self,
        group_id: str | None = None,
        min_strength: int = 3,
        limit: int = 10,
    ) -> list[tuple[str, str, int]]:
        """Return top social pairs as (name_a, name_b, strength) sorted by strength desc.

        Uses a direct Cypher query — no LLM call, no Graphiti search overhead.
        """
        if not self.ready:
            return []
        try:
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
            result = await self._graphiti.driver.execute_query(
                "MATCH (a:Entity {group_id: $gid})-[r:RELATES_TO]-(b:Entity {group_id: $gid}) "
                "WHERE r.invalid_at IS NULL "
                "  AND a.name <> 'unknown' AND b.name <> 'unknown' "
                "  AND a.name <> 'system' AND b.name <> 'system' "
                "  AND NOT a.name CONTAINS '<@' AND NOT b.name CONTAINS '<@' "
                "WITH a.name AS ua, b.name AS ub, count(r) AS strength "
                "WHERE strength >= $min_strength "
                "RETURN ua, ub, strength "
                "ORDER BY strength DESC "
                "LIMIT $limit",
                params={"gid": gid, "min_strength": min_strength, "limit": limit},
            )
            return [
                (record["ua"], record["ub"], record["strength"])
                for record in result.records
            ]
        except Exception as exc:
            logger.warning("Social context query failed: {e}", e=exc)
            return []

    async def get_entity_uuid(self, username: str, group_id: str | None = None) -> str | None:
        """Look up the UUID of a Neo4j entity by username.

        Tries an exact match first, then a CONTAINS fallback.
        Returns None if not found or on error.
        """
        if not self.ready:
            return None
        try:
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
            # Exact match
            result = await self._graphiti.driver.execute_query(
                "MATCH (e:Entity {group_id: $gid}) "
                "WHERE toLower(e.name) = toLower($name) "
                "RETURN e.uuid AS uuid LIMIT 1",
                params={"gid": gid, "name": username},
            )
            if result.records:
                return result.records[0]["uuid"]
            # Fallback: partial match
            result = await self._graphiti.driver.execute_query(
                "MATCH (e:Entity {group_id: $gid}) "
                "WHERE toLower(e.name) CONTAINS toLower($name) "
                "RETURN e.uuid AS uuid LIMIT 1",
                params={"gid": gid, "name": username},
            )
            if result.records:
                return result.records[0]["uuid"]
            return None
        except Exception as exc:
            logger.warning("get_entity_uuid failed for {u}: {e}", u=username, e=exc)
            return None

    async def search_by_entity(
        self,
        query: str,
        center_node_uuid: str,
        limit: int = 8,
        group_id: str | None = None,
    ) -> list[dict]:
        """Search the knowledge graph centred on a specific entity node.

        Filters out invalidated edges (invalid_at is not None).
        Returns list of {"fact": ..., "valid_at": ...} dicts.
        """
        if not self.ready:
            return []
        try:
            gid = self._sanitize_group_id(group_id or self._config.graphiti.group_id)
            edges = await self._graphiti.search(
                query=query,
                group_ids=[gid],
                center_node_uuid=center_node_uuid,
                num_results=limit,
            )
            return [
                {
                    "fact": edge.fact,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                }
                for edge in edges
                if edge.invalid_at is None
            ]
        except Exception as exc:
            logger.warning("search_by_entity failed: {e}", e=exc)
            return []

    async def close(self) -> None:
        """Shutdown Graphiti and close Neo4j connection."""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()
            except Exception:
                pass
            self._graphiti = None
            self._ready = False
