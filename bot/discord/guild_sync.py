"""Parsing de DISCORD_GUILD_ID — module neutre (évite l'import circulaire bot ↔ presence)."""


def parse_guild_ids(raw: str | None) -> list[int]:
    """Parse DISCORD_GUILD_ID (un ou plusieurs IDs séparés par des virgules) → liste d'ints.

    Ces serveurs reçoivent un sync instantané des slash commands (utile pour le dev/test ;
    les commandes globales mettent ~1 h à se propager). Vides, 0 et entrées invalides ignorés.
    """
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            gid = int(part)
        except ValueError:
            continue
        if gid:
            out.append(gid)
    return out
