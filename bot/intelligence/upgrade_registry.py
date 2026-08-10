from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiosqlite
from loguru import logger

# Cycle de vie d'une demande d'amélioration (code_fix).
REQUESTED = "requested"   # émise, en attente d'autorisation / d'exécution
DELIVERED = "delivered"   # acceptée, implémentée et déployée
DECLINED = "declined"     # refusée par le créateur
ABANDONED = "abandoned"   # timeout / échec technique / sans changement (re-proposable)

# Statuts qui BLOQUENT une redemande : une demande encore ouverte, déjà livrée,
# ou explicitement REFUSÉE. Les ABANDONED restent re-proposables (cf. "à
# reproposer" dans self_fix).
#
# DECLINED en était absent : le seul garde-fou contre une redemande refusée était
# un `set` EN MÉMOIRE, perdu à chaque redémarrage — alors que le DM promet
# « Je ne te le reproposerai pas ». Constaté en base : la demande RSS #3
# (2026-07-02) reproposée à l'identique en #14 (2026-07-30).
_BLOCKING = (REQUESTED, DELIVERED, DECLINED)

_STOPWORDS = frozenset(
    {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que",
     "qui", "est", "sur", "pour", "dans", "par", "pas", "ce", "ça", "il",
     "je", "me", "mon", "ma", "mes", "the", "and", "for", "with"}
)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)
    return {t for t in cleaned.split() if len(t) >= 3 and t not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Seuil de recouvrement, et taille minimale pour qu'il s'applique (cf. `_recouvrement`).
_SEUIL_RECOUVREMENT = 0.45
_MIN_TOKENS_RECOUVREMENT = 8


def _recouvrement(a: set[str], b: set[str]) -> float:
    """Part du PLUS PETIT des deux ensembles que l'autre recouvre.

    Insensible à la verbosité, là où `_jaccard` divise par l'union : deux textes
    du même sujet mais de longueurs très différentes s'y reconnaissent quand même.
    C'est ce qui manquait le 2026-08-09 — une redemande deux fois plus longue que
    la demande déjà livrée tombait à 0.215 de Jaccard, sous le seuil, et passait.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass
class UpgradeRow:
    id: int
    proposal: str
    status: str
    created_at: str
    decided_at: str | None = None
    # Ce que la capacité DONNE à Wally, à la première personne et au présent.
    # Renseignée à la livraison ; None pour tout ce qui n'est pas encore livré (et
    # pour les 14 livraisons antérieures au 2026-08-09, d'où le repli au rendu).
    capability: str | None = None


class UpgradeRegistry:
    """Registre durable des demandes d'amélioration de Wally (table
    `pending_upgrades`). Donne à Wally la mémoire de ce qu'il a déjà demandé /
    obtenu, pour ne pas redemander une capacité déjà livrée."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def record_request(self, proposal: str) -> int:
        proposal = (proposal or "").strip()
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """INSERT INTO pending_upgrades (proposal, status, created_at)
                   VALUES (?, ?, ?)""",
                (proposal, REQUESTED, now),
            )
            await db.commit()
            logger.debug("UpgradeRegistry: demande #{} enregistrée — {}", cur.lastrowid, proposal[:60])
            return cur.lastrowid  # type: ignore[return-value]

    async def set_status(self, upgrade_id: int, status: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE pending_upgrades SET status = ?, decided_at = ? WHERE id = ?",
                (status, datetime.utcnow().isoformat(), upgrade_id),
            )
            await db.commit()

    async def reconcile_stale(self, older_than_hours: float) -> int:
        """Passe en ABANDONED les demandes restées REQUESTED trop longtemps.

        À appeler au démarrage. `request_upgrade` attend la réaction de l'owner
        jusqu'à `approval_timeout` (72 h) via un `wait_for` : tout redémarrage
        pendant cette fenêtre — et un self-fix se TERMINE justement par un
        `docker_rebuild` — perd l'attente sans repasser par le
        `except asyncio.TimeoutError` qui aurait posé ABANDONED. La ligne restait
        donc REQUESTED pour toujours, or ce statut est `_BLOCKING` : `find_similar`
        écartant tout ce qui dépasse un Jaccard de 0.3, le but — et tout but
        lexicalement proche — devenait irrattrapable, en silence.

        ABANDONED et non REFUSED : la demande redevient re-proposable, elle n'a
        jamais été refusée par personne.
        """
        limite = (datetime.utcnow() - timedelta(hours=older_than_hours)).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "UPDATE pending_upgrades SET status = ?, decided_at = ? "
                "WHERE status = ? AND created_at < ?",
                (ABANDONED, datetime.utcnow().isoformat(), REQUESTED, limite),
            )
            await db.commit()
            if cur.rowcount:
                logger.info(
                    "UpgradeRegistry: {n} demande(s) restée(s) en suspens rouverte(s)",
                    n=cur.rowcount,
                )
            return cur.rowcount

    async def recent(self, limit: int | None = None) -> list[UpgradeRow]:
        """Historique des demandes, la plus récente d'abord. `limit=None` = tout.

        Sans fenêtre par défaut : la fenêtre de 6 laissait 8 des 14 capacités déjà
        livrées hors de son prompt, et ce sont exactement celles qu'il redemandait
        (statuts Discord, recherche d'historique, digest de réveil…). Le volume
        reste modeste — une vingtaine de lignes tronquées au rendu.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            requete = """SELECT id, proposal, status, created_at, decided_at, capability
                         FROM pending_upgrades ORDER BY created_at DESC"""
            if limit is None:
                cur = await db.execute(requete)
            else:
                cur = await db.execute(requete + " LIMIT ?", (limit,))
            rows = await cur.fetchall()
        return [
            UpgradeRow(id=r["id"], proposal=r["proposal"], status=r["status"],
                       created_at=r["created_at"], decided_at=r["decided_at"],
                       capability=r["capability"])
            for r in rows
        ]

    async def get(self, upgrade_id: int) -> UpgradeRow | None:
        """Une demande par son id, ou None.

        Source DURABLE de ce qui a été demandé — à préférer à un attribut en
        mémoire : la livraison est posée juste après un `docker_rebuild`, donc dans
        une fenêtre où le process peut disparaître à tout instant.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """SELECT id, proposal, status, created_at, decided_at, capability
                   FROM pending_upgrades WHERE id = ?""",
                (upgrade_id,),
            )
            r = await cur.fetchone()
        if r is None:
            return None
        return UpgradeRow(id=r["id"], proposal=r["proposal"], status=r["status"],
                          created_at=r["created_at"], decided_at=r["decided_at"],
                          capability=r["capability"])

    async def set_capability(self, upgrade_id: int, capability: str) -> None:
        """Enregistre ce que la capacité livrée DONNE à Wally, au présent.

        Vide ou blanc → on n'écrit pas : mieux vaut retomber sur la formulation de
        la demande au rendu qu'afficher une ligne creuse.
        """
        capability = (capability or "").strip()
        if not capability:
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE pending_upgrades SET capability = ? WHERE id = ?",
                (capability, upgrade_id),
            )
            await db.commit()

    async def find_similar(
        self, proposal: str, threshold: float = 0.3
    ) -> UpgradeRow | None:
        """Retourne une demande BLOQUANTE (requested/delivered) sémantiquement
        proche de `proposal`, ou None. Sert la garde anti-redemande.

        Deux mesures, chacune rattrapant l'angle mort de l'autre : `_jaccard`
        reconnaît les reformulations de longueur comparable, `_recouvrement`
        reconnaît une redemande DÉLAYÉE (le cas du 2026-08-09). Une seule des
        deux suffit à considérer que c'est le même sujet.

        Le plancher `_MIN_TOKENS_RECOUVREMENT` protège le recouvrement de son
        propre angle mort : une demande de trois mots est « entièrement contenue »
        dans n'importe quelle demande future qui la mentionne au passage, et
        bloquerait alors un sujet bien plus large qu'elle.
        """
        target = _tokens(proposal)
        if not target:
            return None
        placeholders = ",".join("?" * len(_BLOCKING))
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"""SELECT id, proposal, status, created_at, decided_at
                    FROM pending_upgrades WHERE status IN ({placeholders})""",
                _BLOCKING,
            )
            rows = await cur.fetchall()
        best: UpgradeRow | None = None
        best_score = 0.0
        for r in rows:
            autre = _tokens(r["proposal"])
            jac = _jaccard(target, autre)
            rec = (
                _recouvrement(target, autre)
                if min(len(target), len(autre)) >= _MIN_TOKENS_RECOUVREMENT
                else 0.0
            )
            if jac < threshold and rec < _SEUIL_RECOUVREMENT:
                continue
            score = max(jac, rec)
            if score >= best_score:
                best_score = score
                best = UpgradeRow(id=r["id"], proposal=r["proposal"], status=r["status"],
                                  created_at=r["created_at"], decided_at=r["decided_at"])
        return best
