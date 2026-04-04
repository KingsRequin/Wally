from __future__ import annotations

from loguru import logger


async def add_user_fact(
    graph,
    config,
    platform: str,
    user_id: str,
    username: str,
    content: str,
    category: str,
    alias_cache: dict,
) -> None:
    """Write a user fact into the Graphiti knowledge graph.

    Args:
        graph: GraphService instance (must have .ready and .add_episode()).
        config: Config singleton with config.graphiti.group_id.
        platform: Platform identifier ("discord", "twitch").
        user_id: Raw user ID (no prefix, e.g. "610550333042589752").
        username: Human-readable display name.
        content: Fact text to store.
        category: Memory category ("FAIT", "PREF", "LANG", "REL").
        alias_cache: Current alias cache dict (key: "nickname:{name}", value: canonical uid).
    """
    if not graph or not graph.ready:
        return
    try:
        body = f"{username} : {content}"
        raw_uid = f"{platform}:{user_id}"
        known_aliases = [
            alias.split(":", 1)[1]
            for alias, canonical in alias_cache.items()
            if canonical == raw_uid and alias.startswith("nickname:")
        ]
        alias_str = f" Alias connus : {', '.join(known_aliases)}." if known_aliases else ""
        source_desc = f"Souvenir {platform}. Utilisateur : {username} ({raw_uid}).{alias_str}"

        await graph.add_episode(
            content=body,
            author=username,
            source=source_desc,
            group_id=config.graphiti.group_id,
        )
        logger.debug(
            "Graph memory added [{u}|{cat}]: {c}",
            u=username,
            cat=category,
            c=content[:80],
        )
    except Exception as exc:
        logger.warning(
            "graph_memory.add_user_fact failed for {u}: {e}",
            u=username,
            e=exc,
        )


async def search_user_facts(
    graph,
    config,
    username: str,
    query: str,
    limit: int = 8,
) -> str:
    """Search the Graphiti knowledge graph for facts about a user.

    Returns a formatted string of facts (one per line), or "" if none found.

    Args:
        graph: GraphService instance (must have .ready, .get_entity_uuid(),
               .search_by_entity(), and .search()).
        config: Config singleton (unused currently, reserved for future group_id filtering).
        username: Human-readable display name used as entity lookup key.
        query: Search query string.
        limit: Maximum number of results to return (default 8).
    """
    if not graph or not graph.ready:
        return ""
    try:
        uuid = await graph.get_entity_uuid(username)
        if uuid:
            results = await graph.search_by_entity(query, uuid, limit=limit)
        else:
            raw = await graph.search(f"{username} {query}", num_results=limit)
            results = [
                {"fact": r.get("fact", ""), "valid_at": r.get("valid_at")}
                for r in raw
                if r.get("invalid_at") is None
            ]

        if not results:
            return ""

        lines = []
        for r in results:
            fact = r.get("fact", "").strip()
            if not fact:
                continue
            valid_at = r.get("valid_at")
            if valid_at:
                date_part = str(valid_at)[:10]
                lines.append(f"{fact} [depuis {date_part}]")
            else:
                lines.append(fact)
        return "\n".join(lines)
    except Exception as exc:
        logger.warning(
            "graph_memory.search_user_facts failed for {u}: {e}",
            u=username,
            e=exc,
        )
        return ""
