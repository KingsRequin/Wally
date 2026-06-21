# bot/v2/core/memory/facts.py
from __future__ import annotations

import re

import aiosqlite
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger

# Mots vides FR/EN courts ignorés dans les requêtes FTS (réduit le bruit).
_FTS_STOPWORDS: frozenset[str] = frozenset(
    {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "à", "au",
     "the", "a", "an", "of", "to", "is", "it", "in", "on", "for"}
)


def _normalize(s: str) -> str:
    """Normalise une chaîne pour comparer des objects de faits.

    lower + strip + retrait de la ponctuation + collapse des espaces. Sert à
    décider si deux objects désignent la même valeur (`_normalize(a) == _normalize(b)`).
    Conserve les caractères alphanumériques unicode (lettres accentuées incluses)
    et les espaces ; tout le reste (ponctuation, tirets…) est retiré.
    """
    if not s:
        return ""
    lowered = s.lower().strip()
    # Retire la ponctuation (garde lettres/chiffres unicode + espaces).
    cleaned = re.sub(r"[^\w\s]", "", lowered, flags=re.UNICODE)
    # Collapse les espaces multiples.
    return re.sub(r"\s+", " ", cleaned).strip()


def _fts_match_query(query: str) -> str:
    """Transforme une requête libre en expression FTS5 MATCH sûre.

    Chaque terme alphanumérique (≥2 car, hors stopwords) est mis entre guillemets
    et combiné en OR. Évite les erreurs de syntaxe FTS5 dues à la ponctuation.
    Retourne "" si aucun terme exploitable.
    """
    tokens = re.findall(r"\w+", query.lower(), flags=re.UNICODE)
    terms = [t for t in tokens if len(t) >= 2 and t not in _FTS_STOPWORDS]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


class FactCategory(str, Enum):
    FAIT    = "FAIT"
    PREF    = "PREF"
    REL     = "REL"
    LANG    = "LANG"
    DESIRE  = "DESIRE"
    GOAL    = "GOAL"
    EMOTION = "EMOTION"
    THOUGHT = "THOUGHT"


class FactStatus(str, Enum):
    ACTIVE       = "active"
    SUPERSEDED   = "superseded"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED     = "archived"


DECAY_RATES: dict[FactCategory, float] = {
    FactCategory.FAIT:    0.001,
    FactCategory.PREF:    0.005,
    FactCategory.REL:     0.003,
    FactCategory.LANG:    0.001,
    FactCategory.DESIRE:  0.02,
    FactCategory.GOAL:    0.005,
    FactCategory.EMOTION: 0.01,
    FactCategory.THOUGHT: 0.05,
}


@dataclass
class AtomicFact:
    user_id:           str
    content:           str
    category:          FactCategory
    # Triplet sujet-prédicat-objet (porté de jarvis-OS). Optionnel pour
    # rétro-compat : un fait peut n'avoir que `content` (phrase libre).
    subject:           str | None = None
    predicate:         str | None = None
    object_:           str | None = None
    importance:        float = 0.5   # noté par le LLM [0,1], pour le ranking retrieval
    support_count:     int = 1       # nb d'observations confirmant ce fait
    confidence:        float = 1.0
    status:            FactStatus = FactStatus.ACTIVE
    emotional_context: str | None = None
    source:            str = "conversation"
    created_at:        datetime = field(default_factory=datetime.utcnow)
    last_seen_at:      datetime = field(default_factory=datetime.utcnow)
    id:                int | None = None
    decay_rate:        float = field(init=False)

    def __post_init__(self) -> None:
        self.decay_rate = DECAY_RATES.get(self.category, 0.01)


@dataclass
class FactRelation:
    from_id:       int
    to_id:         int
    relation_type: str   # "supersedes" | "contradicts" | "supports"
    created_at:    datetime = field(default_factory=datetime.utcnow)
    id:            int | None = None


class SQLiteFactStore:
    """Accès SQLite pour les AtomicFacts et FactRelations."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def add(self, fact: AtomicFact) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO atomic_facts
                   (user_id, content, category, subject, predicate, object,
                    importance, support_count, confidence, decay_rate, status,
                    emotional_context, source, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fact.user_id, fact.content, fact.category.value,
                    fact.subject, fact.predicate, fact.object_,
                    fact.importance, fact.support_count,
                    fact.confidence, fact.decay_rate, fact.status.value,
                    fact.emotional_context, fact.source,
                    fact.created_at.isoformat(), fact.last_seen_at.isoformat(),
                ),
            )
            await db.commit()
            fact.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_by_user(
        self,
        user_id:        str,
        min_confidence: float = 0.3,
        categories:     list[FactCategory] | None = None,
        status:         FactStatus = FactStatus.ACTIVE,
    ) -> list[AtomicFact]:
        query = (
            "SELECT * FROM atomic_facts "
            "WHERE user_id = ? AND status = ? AND confidence >= ?"
        )
        params: list = [user_id, status.value, min_confidence]
        if categories:
            placeholders = ",".join("?" * len(categories))
            query += f" AND category IN ({placeholders})"
            params.extend(c.value for c in categories)
        query += " ORDER BY last_seen_at DESC, confidence DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def get_by_ids(
        self,
        ids:            list[int],
        min_confidence: float = 0.3,
    ) -> list[AtomicFact]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        query = (
            f"SELECT * FROM atomic_facts "
            f"WHERE id IN ({placeholders}) AND confidence >= ? AND status = ?"
        )
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, [*ids, min_confidence, FactStatus.ACTIVE.value])
            return [self._row_to_fact(r) for r in await cursor.fetchall()]

    async def mark_seen(self, fact_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET last_seen_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), fact_id),
            )
            await db.commit()

    async def delete_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            await db.commit()
            return cursor.rowcount

    async def count_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM atomic_facts WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def apply_decay(self) -> int:
        """Réduit confidence de decay_rate pour tous les faits actifs.
        Archive ceux dont confidence tombe sous 0.1. Retourne le nombre de lignes modifiées.
        """
        async with aiosqlite.connect(self._db_path) as db:
            result = await db.execute(
                """UPDATE atomic_facts
                   SET confidence = MAX(0.0, confidence - decay_rate),
                       status = CASE
                           WHEN MAX(0.0, confidence - decay_rate) < 0.1 THEN 'archived'
                           ELSE status
                       END
                   WHERE status = 'active'"""
            )
            await db.commit()
            return result.rowcount

    async def add_relation(self, relation: FactRelation) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, ?, ?)""",
                (relation.from_id, relation.to_id, relation.relation_type,
                 relation.created_at.isoformat()),
            )
            await db.commit()
            relation.id = cursor.lastrowid
            return cursor.lastrowid  # type: ignore[return-value]

    async def supersede(self, old_id: int, new_id: int) -> None:
        """Marque old_id comme superseded et crée la relation supersedes new_id→old_id.

        Les deux opérations sont atomiques : aiosqlite démarre un BEGIN implicite
        avant le premier DML, et le commit() final valide les deux ensemble.
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET status = 'superseded' WHERE id = ?",
                (old_id,),
            )
            await db.execute(
                """INSERT INTO fact_relations (from_id, to_id, relation_type, created_at)
                   VALUES (?, ?, 'supersedes', ?)""",
                (new_id, old_id, datetime.utcnow().isoformat()),
            )
            await db.commit()
            logger.debug("supersede: fact {} superseded by {}", old_id, new_id)

    async def search_by_category(
        self,
        category: "FactCategory",
        status: "FactStatus | None" = None,
        limit: int = 10,
    ) -> "list[AtomicFact]":
        if status is None:
            status = FactStatus.ACTIVE
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT id, user_id, content, category, confidence, decay_rate,
                          status, emotional_context, source, created_at, last_seen_at
                   FROM atomic_facts
                   WHERE category = ? AND status = ?
                   ORDER BY last_seen_at DESC
                   LIMIT ?""",
                (category.value, status.value, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fact(r) for r in rows]

    async def sample_random(
        self,
        limit: int = 3,
        exclude_category: "FactCategory | None" = None,
    ) -> "list[AtomicFact]":
        """Pioche au hasard des faits ACTIVE (amorce de nouveauté pour la
        cognition idle). `exclude_category` retire une catégorie (ex. THOUGHT,
        pour ne pas ressortir une pensée comme « souvenir »).
        """
        query = (
            "SELECT id, user_id, content, category, confidence, decay_rate, "
            "status, emotional_context, source, created_at, last_seen_at "
            "FROM atomic_facts WHERE status = ?"
        )
        params: list = [FactStatus.ACTIVE.value]
        if exclude_category is not None:
            query += " AND category != ?"
            params.append(exclude_category.value)
        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(limit)
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fact(r) for r in rows]

    @staticmethod
    def _row_to_fact(row: aiosqlite.Row) -> AtomicFact:
        keys = row.keys()

        def _g(name: str, default=None):
            return row[name] if name in keys else default

        fact = AtomicFact(
            user_id=row["user_id"],
            content=row["content"],
            category=FactCategory(row["category"]),
            subject=_g("subject"),
            predicate=_g("predicate"),
            object_=_g("object"),
            importance=_g("importance", 0.5),
            support_count=_g("support_count", 1),
            confidence=row["confidence"],
            status=FactStatus(row["status"]),
            emotional_context=row["emotional_context"],
            source=row["source"] or "conversation",
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )
        fact.id = row["id"]
        # Restore the persisted decay_rate (overrides __post_init__) so that facts
        # keep the rate they were inserted with, even if DECAY_RATES changes later.
        fact.decay_rate = row["decay_rate"]
        return fact

    async def search_fts(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_confidence: float = 0.3,
    ) -> list[tuple[AtomicFact, float]]:
        """Recherche plein-texte BM25 (FTS5) des faits actifs d'un user.

        Retourne des tuples (fait, bm25) triés du plus pertinent au moins
        pertinent. `bm25()` de SQLite renvoie un score où PLUS PETIT = MEILLEUR
        (souvent négatif) ; on trie donc par bm25 croissant. Le filtrage par
        `user_id`/status/confidence se fait via un JOIN sur la table de base.
        """
        match = _fts_match_query(query)
        if not match:
            return []
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                cursor = await db.execute(
                    """SELECT f.*, bm25(atomic_facts_fts) AS rank
                       FROM atomic_facts_fts
                       JOIN atomic_facts f ON f.id = atomic_facts_fts.rowid
                       WHERE atomic_facts_fts MATCH ?
                         AND f.user_id = ? AND f.status = ? AND f.confidence >= ?
                       ORDER BY rank
                       LIMIT ?""",
                    (match, user_id, FactStatus.ACTIVE.value, min_confidence, limit),
                )
                rows = await cursor.fetchall()
            except Exception as exc:  # FTS5 syntax error sur entrée exotique
                logger.warning("search_fts MATCH failed for {!r}: {}", match, exc)
                return []
        return [(self._row_to_fact(r), float(r["rank"])) for r in rows]

    async def set_status(self, fact_id: int, status: FactStatus) -> None:
        """Change le statut d'un fait (ex. GOAL accompli → ARCHIVED)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE atomic_facts SET status = ? WHERE id = ?",
                (status.value, fact_id),
            )
            await db.commit()

    # Séparateur entre l'intitulé d'un but et son journal de progression.
    _PROGRESS_HEADER = "— progression —"

    async def append_progress(
        self, fact_id: int, step: str, max_step_lines: int = 8
    ) -> bool:
        """Journalise une étape concrète DANS le but lui-même (poursuite minimale).

        Charge le fait `fact_id` ; s'il n'existe pas ou n'est pas actif, retourne
        False (log warning). Sinon, ajoute une ligne `· {step}` sous un séparateur
        `— progression —` (créé à la première étape). Garde au plus
        `max_step_lines` lignes de progression (jette les plus anciennes, conserve
        l'intitulé du but). Met à jour `content` + `last_seen_at` ; l'UPDATE
        déclenche le trigger FTS qui ré-indexe automatiquement.
        """
        step = (step or "").strip()
        if not step:
            logger.warning("append_progress: étape vide pour fact #{}", fact_id)
            return False
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT content, status FROM atomic_facts WHERE id = ?", (fact_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                logger.warning("append_progress: fait #{} introuvable", fact_id)
                return False
            if row["status"] != FactStatus.ACTIVE.value:
                logger.warning(
                    "append_progress: fait #{} inactif (status={})",
                    fact_id, row["status"],
                )
                return False

            content: str = row["content"] or ""
            if self._PROGRESS_HEADER in content:
                head, _, progress_block = content.partition(self._PROGRESS_HEADER)
                head = head.rstrip("\n")
                steps = [
                    ln for ln in progress_block.splitlines() if ln.strip()
                ]
            else:
                head = content.rstrip("\n")
                steps = []

            steps.append(f"· {step}")
            # Cap : ne garde que les `max_step_lines` étapes les plus récentes.
            if max_step_lines > 0 and len(steps) > max_step_lines:
                steps = steps[-max_step_lines:]

            new_content = head + "\n" + self._PROGRESS_HEADER + "\n" + "\n".join(steps)
            await db.execute(
                "UPDATE atomic_facts SET content = ?, last_seen_at = ? WHERE id = ?",
                (new_content, datetime.utcnow().isoformat(), fact_id),
            )
            await db.commit()
        logger.debug("append_progress: but #{} +1 étape ({} au total)", fact_id, len(steps))
        return True

    async def confirm(self, fact_id: int) -> None:
        """Renforce un fait existant sans dupliquer (observation CONFIRM) :
        support_count +1, confidence +0.05 (cap 0.99), last_seen_at = maintenant.
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE atomic_facts
                   SET support_count = support_count + 1,
                       confidence    = MIN(0.99, confidence + 0.05),
                       last_seen_at  = ?
                   WHERE id = ?""",
                (datetime.utcnow().isoformat(), fact_id),
            )
            await db.commit()

    async def find_active_match(
        self,
        user_id:   str,
        subject:   str,
        predicate: str,
        category:  FactCategory,
    ) -> AtomicFact | None:
        """Étage 1 de la réconciliation : match déterministe.

        Retourne l'unique fait ACTIVE du même (user_id, subject, predicate,
        category), comparaison de subject/predicate insensible à la casse.
        `None` si aucun. Strictement scopé par user_id (jamais cross-user).
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM atomic_facts
                   WHERE user_id = ? AND status = ? AND category = ?
                     AND LOWER(subject) = LOWER(?)
                     AND LOWER(predicate) = LOWER(?)
                   ORDER BY last_seen_at DESC
                   LIMIT 1""",
                (user_id, FactStatus.ACTIVE.value, category.value,
                 subject, predicate),
            )
            row = await cursor.fetchone()
            return self._row_to_fact(row) if row else None

    async def find_overlap_siblings(
        self,
        user_id:     str,
        subject:     str,
        category:    FactCategory,
        object_text: str,
        limit:       int = 3,
    ) -> list[AtomicFact]:
        """Étage 2 : faits ACTIVE du même user+subject+category dont l'object/
        content recouvre `object_text` (via FTS5). Filtre subject+category côté
        Python (la FTS scope déjà user_id + status). Top `limit`.
        """
        hits = await self.search_fts(user_id, object_text, limit=10)
        subj = _normalize(subject)
        out: list[AtomicFact] = []
        for fact, _score in hits:
            if fact.category != category:
                continue
            if _normalize(fact.subject or "") != subj:
                continue
            out.append(fact)
            if len(out) >= limit:
                break
        return out
