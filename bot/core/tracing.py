"""Langfuse tracing integration — no-op safe when unconfigured."""
from __future__ import annotations

import os
from typing import Any

from loguru import logger

_langfuse: Any = None
_enabled = False


def init_tracing() -> None:
    """Initialize Langfuse client. No-op if keys are missing."""
    global _langfuse, _enabled

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

    if not public_key or not secret_key:
        logger.info("Langfuse tracing disabled (LANGFUSE_PUBLIC_KEY/SECRET_KEY not set)")
        return

    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        _enabled = True
        logger.info("Langfuse tracing enabled — host={host}", host=host)
    except Exception as exc:
        logger.warning("Langfuse init failed: {e}", e=exc)


def shutdown_tracing() -> None:
    """Flush pending traces and shutdown."""
    if _langfuse is not None:
        try:
            _langfuse.flush()
        except Exception as exc:
            logger.debug("Langfuse flush error: {e}", e=exc)


def create_trace(
    name: str,
    user_id: str | None = None,
    platform: str | None = None,
    channel_id: str | None = None,
    metadata: dict | None = None,
) -> Any | None:
    """Create a Langfuse trace. Returns None if tracing is disabled."""
    if not _enabled or _langfuse is None:
        return None
    try:
        meta = metadata or {}
        if platform:
            meta["platform"] = platform
        if channel_id:
            meta["channel_id"] = channel_id
        return _langfuse.trace(
            name=name,
            user_id=user_id,
            metadata=meta,
        )
    except Exception as exc:
        logger.debug("Langfuse create_trace error: {e}", e=exc)
        return None


def create_generation(
    trace: Any,
    name: str,
    model: str,
    input: Any = None,
    output: str | None = None,
    usage: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Log an LLM generation (call) within a trace. No-op if trace is None."""
    if trace is None:
        return
    try:
        trace.generation(
            name=name,
            model=model,
            input=input,
            output=output,
            usage=usage,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("Langfuse create_generation error: {e}", e=exc)


def create_span(
    trace: Any,
    name: str,
    input: Any = None,
    output: Any = None,
    metadata: dict | None = None,
) -> None:
    """Log a non-LLM operation span within a trace. No-op if trace is None."""
    if trace is None:
        return
    try:
        trace.span(
            name=name,
            input=input,
            output=output,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("Langfuse create_span error: {e}", e=exc)
