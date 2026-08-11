from __future__ import annotations

import time
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass


class ApexMixin:
    """Les comptes Apex déclarés par les gens.

    Un compte par personne : `identity` (« twitch:123 », « discord:456 ») est la
    clé. `display_name` garde le pseudo de plateforme au moment de la liaison,
    pour que « les stats de xeforce » retrouve le compte sans dépendre du
    système d'alias.
    """

    _conn: aiosqlite.Connection

    # Déclarés pour le type-check (implémentés dans Database)
    async def fetch_one(self, query: str, params=()) -> "aiosqlite.Row | None": ...
    async def execute(self, query: str, params=()): ...
    async def fetch_all(self, query: str, params=()): ...

    async def apex_link_account(
        self,
        *,
        identity: str,
        display_name: str,
        apex_name: str,
        apex_platform: str,
        uid: str | None = None,
    ) -> None:
        """Associe un compte Apex à quelqu'un. Redéclarer remplace l'ancien."""
        await self.execute(
            """
            INSERT INTO apex_accounts (identity, display_name, apex_name, apex_platform, uid, linked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity) DO UPDATE SET
                display_name = excluded.display_name,
                apex_name    = excluded.apex_name,
                apex_platform= excluded.apex_platform,
                uid          = excluded.uid,
                linked_at    = excluded.linked_at
            """,
            (identity, display_name, apex_name, apex_platform, uid, time.time()),
        )

    async def apex_get_account(self, identity: str) -> "aiosqlite.Row | None":
        return await self.fetch_one(
            "SELECT * FROM apex_accounts WHERE identity = ?", (identity,)
        )

    async def apex_find_by_display_name(self, display_name: str) -> "aiosqlite.Row | None":
        """Le compte de la personne qui portait ce pseudo, casse ignorée.

        La correspondance EXACTE d'abord — c'est la plus sûre. À défaut, on
        rapproche par ressemblance : personne n'écrit « azrael_ttv » dans une
        phrase, on dit « azra » ou « Azraël ». Sans ce repli, « les kills de
        azra » n'atteignait aucun compte connu et partait interroger l'API sur
        un pseudo qu'elle ne connaît pas.
        """
        if not display_name:
            return None
        exact = await self.fetch_one(
            "SELECT * FROM apex_accounts WHERE lower(display_name) = lower(?) "
            "ORDER BY linked_at DESC LIMIT 1",
            (display_name,),
        )
        if exact is not None:
            return exact
        return await self._apex_find_approchant(display_name)

    async def _apex_find_approchant(self, nom: str) -> "aiosqlite.Row | None":
        """Le compte lié dont un des noms ressemble le plus à `nom`, ou None.

        `matches_name` sert déjà à retrouver le clippeur d'un clip depuis un
        surnom : même besoin, même règle — et son plancher de trois caractères
        évite qu'« az » ne désigne le premier venu.

        On compare au pseudo de PLATEFORME comme au pseudo APEX : les deux sont
        cités indifféremment dans une phrase.
        """
        from bot.core.account_linker import matches_name, score

        rows = await self.fetch_all("SELECT * FROM apex_accounts")
        meilleur, meilleur_score = None, 0.0
        for row in rows or []:
            for champ in ("display_name", "apex_name"):
                candidat = str(row[champ] or "")
                if not candidat or not matches_name(candidat, nom):
                    continue
                s = score(candidat, nom)
                if s > meilleur_score:
                    meilleur, meilleur_score = row, s
        return meilleur
