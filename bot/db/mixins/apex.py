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

    # ── Le registre des profils croisés ──────────────────────────────────────

    async def apex_remember_profile(
        self, *, uid: str, apex_name: str, platform: str, saisi: str = ""
    ) -> None:
        """Consigne un profil vu, et le(s) nom(s) sous le(s)quel(s) on l'a vu.

        `saisi` est le pseudo que la personne a employé. Il compte autant que le
        nom officiel : c'est lui qu'on redira la prochaine fois, et l'API ne
        sait pas forcément le résoudre — c'est même tout l'intérêt du registre.
        """
        if not uid or not apex_name:
            return
        maintenant = time.time()
        await self.execute(
            """
            INSERT INTO apex_profiles (uid, apex_name, platform, first_seen, last_seen, seen_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(uid) DO UPDATE SET
                apex_name  = excluded.apex_name,
                platform   = excluded.platform,
                last_seen  = excluded.last_seen,
                seen_count = seen_count + 1
            """,
            (uid, apex_name, platform or "PC", maintenant, maintenant),
        )
        for nom in {apex_name, saisi.strip()} - {""}:
            await self.execute(
                "INSERT INTO apex_profile_names (uid, name, seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT(uid, name) DO UPDATE SET seen_at = excluded.seen_at",
                (uid, nom, maintenant),
            )

    async def apex_uid_pour_nom(self, nom: str) -> dict | None:
        """Le profil déjà croisé que ce nom désigne, ou None.

        Rend `exact` : un rapprochement approximatif doit pouvoir être ANNONCÉ,
        avec le lien du profil, plutôt que d'être servi comme une certitude —
        deux joueurs peuvent porter des pseudos voisins et personne ne valide
        derrière.
        """
        nom = (nom or "").strip()
        if not nom:
            return None
        exact = await self.fetch_one(
            "SELECT p.uid, p.apex_name, p.platform FROM apex_profile_names n "
            "JOIN apex_profiles p ON p.uid = n.uid "
            "WHERE n.name = ? ORDER BY n.seen_at DESC LIMIT 1",
            (nom,),
        )
        if exact is not None:
            return {**dict(exact), "exact": True}
        return await self._apex_profil_approchant(nom)

    async def apex_list_profiles(self) -> list[dict]:
        """Tout le registre, chaque profil avec ses noms et son propriétaire.

        Deux requêtes plutôt qu'un `GROUP_CONCAT` : un pseudo peut contenir
        n'importe quel caractère, y compris celui qui servirait de séparateur.
        """
        profils = await self.fetch_all(
            "SELECT uid, apex_name, platform, first_seen, last_seen, seen_count "
            "FROM apex_profiles ORDER BY last_seen DESC"
        )
        noms: dict[str, list[str]] = {}
        for row in await self.fetch_all(
            "SELECT uid, name FROM apex_profile_names ORDER BY seen_at DESC"
        ) or []:
            noms.setdefault(row["uid"], []).append(row["name"])
        # Les propriétaires sont agrégés APRÈS coup, jamais par jointure : une
        # même personne est déclarée sur ses DEUX identités (le vocal la
        # reconnaît en Discord, le chat en Twitch), et un `LEFT JOIN` rendait
        # alors le profil en double — vu en prod dès la première ouverture.
        proprietaires: dict[str, list[dict]] = {}
        for row in await self.fetch_all(
            "SELECT uid, identity, display_name FROM apex_accounts WHERE uid IS NOT NULL"
        ) or []:
            proprietaires.setdefault(row["uid"], []).append(
                {"identity": row["identity"], "display_name": row["display_name"]}
            )
        return [
            {
                "uid": r["uid"],
                "apex_name": r["apex_name"],
                "platform": r["platform"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "seen_count": r["seen_count"],
                "names": noms.get(r["uid"], []),
                "owners": proprietaires.get(r["uid"], []),
            }
            for r in profils or []
        ]

    async def apex_forget_name(self, uid: str, name: str) -> bool:
        """Retire un nom qui menait à ce profil. Faux si rien n'a été retiré."""
        avant = await self.fetch_one(
            "SELECT count(*) AS n FROM apex_profile_names WHERE uid = ? AND name = ?",
            (uid, name),
        )
        if not avant or not avant["n"]:
            return False
        await self.execute(
            "DELETE FROM apex_profile_names WHERE uid = ? AND name = ?", (uid, name)
        )
        return True

    async def apex_forget_profile(self, uid: str) -> None:
        """Retire un profil ET ses noms — sinon les alias resteraient orphelins
        et continueraient de rapprocher au nom d'un profil disparu."""
        await self.execute("DELETE FROM apex_profile_names WHERE uid = ?", (uid,))
        await self.execute("DELETE FROM apex_profiles WHERE uid = ?", (uid,))

    async def apex_unlink_account(self, identity: str) -> None:
        """Défait la liaison personne ↔ compte. Le registre, lui, garde le
        profil : ce que Wally a croisé reste vrai, seule l'appartenance change."""
        await self.execute("DELETE FROM apex_accounts WHERE identity = ?", (identity,))

    async def _apex_profil_approchant(self, nom: str) -> dict | None:
        """Le profil dont un des noms connus ressemble le plus à `nom`.

        Même règle que pour les comptes déclarés : `matches_name` et son
        plancher de trois caractères, pour qu'« az » ne désigne pas le premier
        venu.
        """
        from bot.core.account_linker import matches_name, score

        rows = await self.fetch_all(
            "SELECT n.name, p.uid, p.apex_name, p.platform FROM apex_profile_names n "
            "JOIN apex_profiles p ON p.uid = n.uid"
        )
        meilleur, meilleur_score = None, 0.0
        for row in rows or []:
            candidat = str(row["name"] or "")
            if not candidat or not matches_name(candidat, nom):
                continue
            s = score(candidat, nom)
            if s > meilleur_score:
                meilleur, meilleur_score = row, s
        if meilleur is None:
            return None
        return {
            "uid": meilleur["uid"],
            "apex_name": meilleur["apex_name"],
            "platform": meilleur["platform"],
            "exact": False,
        }

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
