from __future__ import annotations

import json

import aiosqlite


class TcgMixin:
    """Les decks Wallycard, rangés par compte Discord.

    🚨 Chaque requête porte le `discord_id` dans son WHERE, lecture comprise. Le
    cloisonnement entre comptes vit ICI et pas dans la route : une route qui
    chargerait un deck par son seul `id` puis comparerait le propriétaire
    laisserait la prochaine route oublier la comparaison.

    Les listes de clés sont rangées en JSON. Elles sont petites, toujours lues
    ensemble, et jamais filtrées en SQL : une table de liaison coûterait des
    jointures pour rien.
    """

    _conn: aiosqlite.Connection

    @staticmethod
    def _deck(ligne: aiosqlite.Row) -> dict:
        return {
            "id": ligne["id"],
            "nom": ligne["nom"],
            "heros": json.loads(ligne["heros"]),
            "cartes": json.loads(ligne["cartes"]),
            "modifie_le": ligne["modifie_le"],
        }

    async def lister_decks(self, discord_id: str) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM tcg_decks WHERE discord_id = ? "
            "ORDER BY modifie_le DESC, id DESC",
            (discord_id,),
        ) as curseur:
            return [self._deck(ligne) for ligne in await curseur.fetchall()]

    async def compter_decks(self, discord_id: str) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) AS n FROM tcg_decks WHERE discord_id = ?", (discord_id,),
        ) as curseur:
            ligne = await curseur.fetchone()
        return int(ligne["n"]) if ligne else 0

    async def lire_deck(self, deck_id: int, discord_id: str) -> dict | None:
        async with self._conn.execute(
            "SELECT * FROM tcg_decks WHERE id = ? AND discord_id = ?", (deck_id, discord_id),
        ) as curseur:
            ligne = await curseur.fetchone()
        return self._deck(ligne) if ligne else None

    async def creer_deck(self, discord_id: str, nom: str,
                         heros: list[str], cartes: list[str]) -> int:
        curseur = await self._conn.execute(
            "INSERT INTO tcg_decks (discord_id, nom, heros, cartes) VALUES (?, ?, ?, ?)",
            (discord_id, nom, json.dumps(heros), json.dumps(cartes)),
        )
        await self._conn.commit()
        return int(curseur.lastrowid or 0)

    async def modifier_deck(self, deck_id: int, discord_id: str, nom: str,
                            heros: list[str], cartes: list[str]) -> bool:
        curseur = await self._conn.execute(
            "UPDATE tcg_decks SET nom = ?, heros = ?, cartes = ?, "
            "modifie_le = datetime('now') WHERE id = ? AND discord_id = ?",
            (nom, json.dumps(heros), json.dumps(cartes), deck_id, discord_id),
        )
        await self._conn.commit()
        return curseur.rowcount > 0

    async def supprimer_deck(self, deck_id: int, discord_id: str) -> bool:
        curseur = await self._conn.execute(
            "DELETE FROM tcg_decks WHERE id = ? AND discord_id = ?", (deck_id, discord_id))
        await self._conn.commit()
        return curseur.rowcount > 0
