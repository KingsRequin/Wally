"""Le registre des salons vocaux temporaires (`bot/discord/salons_temporaires.py`).

Il remplace le `data/voice_channels.json` du bot Node `wally-discord`. Le
registre est ce qui distingue un salon créé par Wally — qu'il peut supprimer
quand il se vide — d'un salon vocal ordinaire, qu'il ne doit jamais toucher.
"""
from __future__ import annotations

import time

import aiosqlite


class SalonsMixin:
    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database). `raise` plutôt
    # que `...` : mypy exige un `return` explicite sur un corps vide dès que
    # le type de retour n'est pas `None` (cf. `scripts/lint_types.py`).
    async def fetch_all(self, query: str, params=()) -> list:
        raise NotImplementedError

    async def execute(self, query: str, params=()) -> None:
        raise NotImplementedError

    async def salon_temporaire_ajouter(self, channel_id: int, guild_id: int) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO salons_vocaux_temporaires "
            "(channel_id, guild_id, created_at) VALUES (?, ?, ?)",
            (str(channel_id), str(guild_id), time.time()),
        )

    async def salon_temporaire_retirer(self, channel_id: int) -> None:
        await self.execute(
            "DELETE FROM salons_vocaux_temporaires WHERE channel_id = ?",
            (str(channel_id),),
        )

    async def salons_temporaires(self) -> set[int]:
        rows = await self.fetch_all("SELECT channel_id FROM salons_vocaux_temporaires")
        return {int(r["channel_id"]) for r in rows}
