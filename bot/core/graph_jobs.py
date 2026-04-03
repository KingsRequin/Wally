"""Scheduled graph maintenance jobs (community detection, etc.)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bot.core.graph import GraphService


async def _run_community_detection(graph: "GraphService") -> None:
    """Trigger Graphiti community detection via a synthetic episode."""
    if not graph.ready:
        logger.debug("Community detection skipped — graph not ready")
        return
    try:
        result = await graph.add_episode(
            content="Mise à jour des communautés sociales du serveur.",
            author="system",
            source="system",
            update_communities=True,
        )
        logger.info("Community detection completed: {r}", r=result)
    except Exception as exc:
        logger.warning("Community detection job failed: {e}", e=exc)


def schedule_community_detection(graph: "GraphService", scheduler) -> None:
    """Add a nightly community detection job to the shared scheduler.

    Runs every night at 03:00 UTC.
    """
    scheduler.add_job(
        _run_community_detection,
        "cron",
        hour=3,
        minute=0,
        args=[graph],
        id="community_detection_nightly",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Community detection job scheduled (daily at 03:00 UTC)")
