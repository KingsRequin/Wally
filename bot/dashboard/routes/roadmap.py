# bot/dashboard/routes/roadmap.py
"""Parse ROADMAP.md and expose a structured roadmap API."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

ROADMAP_PATH = Path(__file__).parents[3] / "ROADMAP.md"


def _parse_roadmap() -> dict:
    """Parse ROADMAP.md into structured sections with items."""
    if not ROADMAP_PATH.exists():
        return {"sections": [], "stats": {"total": 0, "done": 0}}

    text = ROADMAP_PATH.read_text(encoding="utf-8")

    sections: list[dict] = []
    current_section: dict | None = None
    current_item: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Skip title
        if line.startswith("# "):
            continue

        # Section headers: ##
        section_match = re.match(r"^##\s+(.+)$", line)
        if section_match:
            current_section = {"title": section_match.group(1).strip(), "items": []}
            sections.append(current_section)
            current_item = None
            continue

        if current_section is None:
            continue

        # Top-level items: - [ ] or - [x]
        item_match = re.match(r"^- \[([ xX])\]\s+(.+)$", line)
        if item_match:
            done = item_match.group(1).lower() == "x"
            current_item = {
                "title": item_match.group(2).strip(),
                "done": done,
                "description": None,
                "sub_items": [],
            }
            current_section["items"].append(current_item)
            continue

        # Sub-items: indented - [ ] or - [x]
        sub_match = re.match(r"^\s+- \[([ xX])\]\s+(.+)$", line)
        if sub_match and current_item is not None:
            done = sub_match.group(1).lower() == "x"
            current_item["sub_items"].append({
                "title": sub_match.group(2).strip(),
                "done": done,
            })
            continue

        # Description: indented plain text (not a list item)
        if current_item is not None and line.startswith("  ") and line.strip():
            desc = line.strip()
            if current_item["description"]:
                current_item["description"] += " " + desc
            else:
                current_item["description"] = desc

    # Compute stats
    total = 0
    done = 0
    for section in sections:
        for item in section["items"]:
            total += 1
            if item["done"]:
                done += 1
            for sub in item["sub_items"]:
                total += 1
                if sub["done"]:
                    done += 1

    return {"sections": sections, "stats": {"total": total, "done": done}}


@router.get("/roadmap")
async def get_roadmap() -> dict:
    """Return the parsed roadmap from ROADMAP.md."""
    return _parse_roadmap()
