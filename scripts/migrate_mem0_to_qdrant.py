#!/usr/bin/env python3
"""Migrate mem0 payloads to structured format in Qdrant.

Reads existing points, rewrites payloads with structured metadata.
Vectors are NOT changed — only payloads are updated.
Idempotent: safe to run multiple times.

Usage:
    python scripts/migrate_mem0_to_qdrant.py [--dry-run] [--url=http://localhost:6333]
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from qdrant_client import QdrantClient

COLLECTION = "wally_memory"
DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]")


def migrate(qdrant_url: str = "http://localhost:6333", dry_run: bool = False) -> None:
    client = QdrantClient(url=qdrant_url)

    if not client.collection_exists(COLLECTION):
        print(f"Collection '{COLLECTION}' does not exist. Nothing to migrate.")
        return

    offset = None
    migrated = 0
    skipped = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION,
            limit=100,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

        if not points:
            break

        for point in points:
            payload = point.payload or {}

            # Already migrated?
            if "text" in payload and "source" in payload:
                skipped += 1
                continue

            # Extract text from mem0 format ("data" is the actual mem0 field)
            text = payload.get("data", payload.get("memory", payload.get("text", "")))
            if not text:
                skipped += 1
                continue

            # Extract user_id
            user_id = payload.get("user_id", "")
            if not user_id:
                skipped += 1
                continue

            # Parse platform from user_id
            parts = user_id.split(":", 1)
            platform = parts[0] if len(parts) == 2 else "unknown"

            # Parse date from text prefix [YYYY-MM-DD]
            date_match = DATE_RE.match(text)
            date_str = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Build new payload
            new_payload = {
                "text": text,
                "user_id": user_id,
                "category": payload.get("category", "FAIT"),
                "date": date_str,
                "source": "legacy_mem0",
                "platform": platform,
                "created_at": payload.get("created_at", datetime.now(timezone.utc).isoformat()),
            }

            if not dry_run:
                # overwrite_payload replaces entire payload (removes old mem0 fields)
                client.overwrite_payload(
                    collection_name=COLLECTION,
                    payload=new_payload,
                    points=[point.id],
                )
            migrated += 1

        if next_offset is None:
            break
        offset = next_offset

    mode = " (DRY RUN)" if dry_run else ""
    print(f"Migration complete{mode}: {migrated} migrated, {skipped} skipped")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    url = "http://localhost:6333"
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            url = arg.split("=", 1)[1]
    migrate(url, dry_run=dry)
