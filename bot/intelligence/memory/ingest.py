# bot/intelligence/memory/ingest.py
"""Pipeline d'ingestion mémoire : contenu → faits (LLM) → réconciliation 2 étages.

Porté/adapté de jarvis-OS (`MemoryIngest`). jarvis est sync + mono-user ; Wally est
**async + multi-user** : chaque requête est strictement scopée par `user_id` (jamais
de fuite cross-user). Les catégories sont celles de Wally (`FactCategory`).

Réconciliation (anti-doublon) en deux étages :

- **Étage 1 — déterministe (zéro LLM)** : `find_active_match(user_id, subject,
  predicate, category)`. Si trouvé et object normalisé identique → `confirm`
  (support_count +1, pas de doublon). Si object différent sur catégorie *stable*
  (identité/relations/objectifs) → arbitre LLM ; sur catégorie *volatile*
  (préférences/émotions/pensées) → coexistence sans arbitrage.
- **Étage 2 — arbitre LLM** : pas de match exact mais recouvrement FTS5 avec un
  sibling (même subject+category). L'arbitre tranche same_as / contradicts / new.

Confidence initiale par origine : explicit 0.7, inference 0.55, correction 0.8.
Tout doute de l'arbitre → `new` (refus prudent du faux positif).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from bot.intelligence.memory.facts import (
    AtomicFact,
    FactCategory,
    FactStatus,
    SQLiteFactStore,
    _normalize,
)
from bot.intelligence.memory.vocab import CATEGORIES, PREDICATES

# ── Constantes ────────────────────────────────────────────────────────────────

# Confidence initiale selon l'origine déclarée par l'extracteur.
_CONFIDENCE_BY_SOURCE: dict[str, float] = {
    "explicit": 0.7,
    "inference": 0.55,
    "correction": 0.8,
}

# Catégories "stables" : une contradiction sur ces catégories déclenche une
# supersession (identité, relations, objectifs, langue, désirs profonds). Sur les
# autres (PREF, EMOTION, THOUGHT — volatiles), on tolère la coexistence : plusieurs
# préférences/émotions/opinions peuvent cohabiter sans se contredire.
_STABLE_CATEGORIES: frozenset[FactCategory] = frozenset(
    {
        FactCategory.FAIT,
        FactCategory.REL,
        FactCategory.GOAL,
        FactCategory.LANG,
        FactCategory.DESIRE,
    }
)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "persona" / "prompts"

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)
_VALID_VERDICTS = {"same_as", "contradicts", "new"}

# Fallbacks inline si les fichiers de prompt sont absents (garde le module
# autonome ; les .md restent la source de vérité éditable).
_EXTRACT_FALLBACK = (
    "Tu extrais des faits atomiques (S-P-O + catégorie) en JSON strict "
    '{"facts":[...]}. predicate dans : {predicates}. category dans : {categories}. '
    "0 à 5 faits, liste vide si rien."
)
_ARBITER_FALLBACK = (
    "Tu es un arbitre de réconciliation mémoire. Réponds en JSON strict "
    '{"verdict":"same_as|contradicts|new","target_fact_id":...}.'
)


def _load_prompt(name: str, fallback: str) -> str:
    try:
        return (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    except OSError:
        logger.warning("ingest: prompt {} introuvable, fallback inline", name)
        return fallback


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class IngestResult:
    """Trace d'une ingestion (pour télémétrie/tests)."""

    confirmed:           list[AtomicFact] = field(default_factory=list)
    superseded_pairs:    list[tuple[AtomicFact, AtomicFact]] = field(default_factory=list)
    new_facts:           list[AtomicFact] = field(default_factory=list)
    needs_review:        list[AtomicFact] = field(default_factory=list)
    raw_extracted_count: int = 0


@dataclass
class _Candidate:
    """Fait candidat extrait par le LLM, avant réconciliation."""

    subject:           str
    predicate:         str
    object:            str  # noqa: A003
    category:          str
    confidence_source: str
    importance:        float


@dataclass
class _Verdict:
    kind:           str  # same_as | contradicts | new
    target_fact_id: int | None = None


# ── Pipeline ──────────────────────────────────────────────────────────────────


class MemoryIngest:
    """Extraction LLM + réconciliation anti-doublon, scopée par user_id.

    `arbiter_calls` : compteur d'appels au LLM arbitre (télémétrie/coût).
    """

    def __init__(
        self,
        store: SQLiteFactStore,
        llm,
        name_hint: str | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._name_hint = name_hint
        self._extract_system = _load_prompt("memory_extract.md", _EXTRACT_FALLBACK)
        self._arbiter_system = _load_prompt("memory_arbiter.md", _ARBITER_FALLBACK)
        self.arbiter_calls = 0

    async def ingest(
        self,
        user_id: str,
        content: str,
        source: str = "conversation",
        subject_hint: str | None = None,
    ) -> IngestResult:
        """Extrait les faits du `content` puis réconcilie chacun. Tout est scopé
        au `user_id` fourni."""
        candidates = await self._extract_facts(content, source, user_id)
        result = IngestResult(raw_extracted_count=len(candidates))

        for cand in candidates:
            outcome = await self._reconcile(cand, user_id)
            kind = outcome[0]
            if kind == "confirmed":
                result.confirmed.append(outcome[1])
            elif kind == "superseded":
                result.superseded_pairs.append((outcome[2], outcome[1]))
                result.new_facts.append(outcome[1])
            elif kind == "new":
                result.new_facts.append(outcome[1])
            elif kind == "needs_review":
                result.needs_review.append(outcome[1])

        logger.debug(
            "ingest user={} : {} extraits → {} new, {} confirm, {} superseded, {} review",
            user_id, result.raw_extracted_count, len(result.new_facts),
            len(result.confirmed), len(result.superseded_pairs), len(result.needs_review),
        )
        return result

    # ── Étape 1 : extraction LLM ──────────────────────────────────────────────

    async def _extract_facts(
        self, content: str, source: str, user_id: str
    ) -> list[_Candidate]:
        system = self._extract_system.replace(
            "{predicates}", ", ".join(sorted(PREDICATES))
        ).replace("{categories}", ", ".join(sorted(CATEGORIES)))
        user_msg = f"Source : {source}\nÉchange à analyser :\n{content}"
        try:
            raw = await self._llm.complete(
                system, [{"role": "user", "content": user_msg}]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ingest: extraction LLM échouée: {}", exc)
            return []
        if not isinstance(raw, str):
            return []
        return _parse_extract_response(raw)

    # ── Point d'entrée public : réconciliation d'un candidat déjà extrait ──────

    async def reconcile_candidate(self, user_id: str, cand: _Candidate) -> tuple:
        """Réconcilie un candidat S-P-O DÉJÀ extrait (saute l'extraction LLM).

        Permet à fact_extractor (qui fait sa propre extraction multi-user) de
        réutiliser la réconciliation 2 étages. `user_id` doit déjà être préfixé
        (`discord:<id>`). Retourne le même tuple que `_reconcile`.
        """
        return await self._reconcile(cand, user_id)

    # ── Étape 2 : réconciliation 2 étages ─────────────────────────────────────

    async def _reconcile(self, cand: _Candidate, user_id: str):
        # Hors vocabulaire → needs_review (jamais en base principale active).
        if cand.predicate not in PREDICATES or cand.category not in CATEGORIES:
            fact = self._make_fact(cand, user_id, FactStatus.NEEDS_REVIEW)
            await self._store.add(fact)
            return ("needs_review", fact)

        category = FactCategory(cand.category)

        # ── Étage 1 — match déterministe ──────────────────────────────────────
        match = await self._store.find_active_match(
            user_id, cand.subject, cand.predicate, category
        )
        if match is not None:
            if _normalize(cand.object) == _normalize(match.object_ or ""):
                await self._confirm(match)
                return ("confirmed", match)

            # Object différent. Catégorie stable → arbitre ; volatile → coexiste.
            if category in _STABLE_CATEGORIES:
                verdict = await self._arbitrate(cand, [match])
                if verdict.kind == "same_as":
                    await self._confirm(match)
                    return ("confirmed", match)
                if verdict.kind == "contradicts":
                    new = await self._supersede(match, cand, user_id)
                    return ("superseded", new, match)
                # "new" → coexistence (rare sur stable mais possible)
            new = self._make_fact(cand, user_id, FactStatus.ACTIVE)
            await self._store.add(new)
            return ("new", new)

        # ── Étage 2 — pas de match exact : siblings via FTS5 ───────────────────
        siblings = await self._store.find_overlap_siblings(
            user_id, cand.subject, category, cand.object
        )
        if siblings:
            verdict = await self._arbitrate(cand, siblings)
            target = next(
                (s for s in siblings if s.id == verdict.target_fact_id), None
            )
            if verdict.kind == "same_as" and target is not None:
                await self._confirm(target)
                return ("confirmed", target)
            if (
                verdict.kind == "contradicts"
                and target is not None
                and target.category in _STABLE_CATEGORIES
            ):
                new = await self._supersede(target, cand, user_id)
                return ("superseded", new, target)

        # Fallback : nouveau fait.
        new = self._make_fact(cand, user_id, FactStatus.ACTIVE)
        await self._store.add(new)
        return ("new", new)

    # ── Arbitre LLM ───────────────────────────────────────────────────────────

    async def _arbitrate(
        self, cand: _Candidate, possibles: list[AtomicFact]
    ) -> _Verdict:
        """Appelle le LLM arbitre. Doute/erreur → "new" (prudence)."""
        self.arbiter_calls += 1
        lines = [
            "## Fait candidat",
            f"  subject:   {cand.subject}",
            f"  predicate: {cand.predicate}",
            f"  object:    {cand.object}",
            f"  category:  {cand.category}",
            "",
            "## Faits existants ACTIFS (même sujet, même catégorie)",
        ]
        for f in possibles:
            lines.append(
                f"  [{f.id}]  {f.subject} {f.predicate} {f.object_}  "
                f"(conf {f.confidence:.2f}, vu {f.support_count}×)"
            )
        lines.append("")
        lines.append(
            'Réponds : {"verdict":"same_as|contradicts|new","target_fact_id":<id> ou null}'
        )
        user_msg = "\n".join(lines)
        try:
            raw = await self._llm.complete(
                self._arbiter_system, [{"role": "user", "content": user_msg}]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ingest: arbitre LLM échoué → 'new': {}", exc)
            return _Verdict("new")
        if not isinstance(raw, str):
            return _Verdict("new")
        return _parse_arbiter_verdict(raw)

    # ── Mutations base ────────────────────────────────────────────────────────

    async def _confirm(self, existing: AtomicFact) -> None:
        await self._store.confirm(existing.id)
        # Reflète le renforcement sur l'objet en mémoire (pour le résultat).
        existing.support_count += 1
        existing.confidence = min(0.99, existing.confidence + 0.05)

    async def _supersede(
        self, old: AtomicFact, cand: _Candidate, user_id: str
    ) -> AtomicFact:
        new = self._make_fact(cand, user_id, FactStatus.ACTIVE)
        new_id = await self._store.add(new)
        await self._store.supersede(old.id, new_id)
        old.status = FactStatus.SUPERSEDED
        return new

    def _make_fact(
        self, cand: _Candidate, user_id: str, status: FactStatus
    ) -> AtomicFact:
        category = (
            FactCategory(cand.category)
            if cand.category in CATEGORIES
            else FactCategory.FAIT
        )
        confidence = _CONFIDENCE_BY_SOURCE.get(cand.confidence_source, 0.55)
        content = _render_content(cand)
        return AtomicFact(
            user_id=user_id,
            content=content,
            category=category,
            subject=cand.subject,
            predicate=cand.predicate,
            object_=cand.object,
            importance=max(0.0, min(1.0, cand.importance)),
            confidence=confidence,
            status=status,
            source="ingest",
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _render_content(cand: _Candidate) -> str:
    """Rend une phrase lisible du triplet (sert au FTS et à l'affichage)."""
    parts = [p for p in (cand.subject, cand.predicate, cand.object) if p]
    return " ".join(parts).strip()


def _parse_extract_response(raw: str) -> list[_Candidate]:
    """Extrait la liste `facts` d'une réponse LLM (tolère ```json``` et bruit)."""
    text = raw.strip()
    fence = _CODE_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    match = _JSON_OBJ_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.debug("ingest: JSON extraction invalide: {}", exc)
        return []
    if not isinstance(data, dict):
        return []
    raw_facts = data.get("facts", [])
    if not isinstance(raw_facts, list):
        return []
    out: list[_Candidate] = []
    for item in raw_facts[:5]:
        if not isinstance(item, dict):
            continue
        subj = item.get("subject")
        pred = item.get("predicate")
        obj = item.get("object")
        cat = item.get("category")
        if not all(isinstance(x, str) and x.strip() for x in (subj, pred, obj, cat)):
            continue
        try:
            imp = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            imp = 0.5
        out.append(
            _Candidate(
                subject=subj.strip(),
                predicate=pred.strip(),
                object=obj.strip(),
                category=cat.strip(),
                confidence_source=str(item.get("confidence_source", "inference")),
                importance=imp,
            )
        )
    return out


def _parse_arbiter_verdict(raw: str) -> _Verdict:
    """Parse le verdict arbitre. Tout doute → "new"."""
    text = raw.strip()
    fence = _CODE_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    match = _JSON_OBJ_RE.search(text)
    if not match:
        return _Verdict("new")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return _Verdict("new")
    if not isinstance(data, dict):
        return _Verdict("new")
    verdict = data.get("verdict", "new")
    if verdict not in _VALID_VERDICTS:
        return _Verdict("new")
    target = data.get("target_fact_id")
    try:
        target_id = int(target) if target is not None else None
    except (TypeError, ValueError):
        target_id = None
    return _Verdict(kind=verdict, target_fact_id=target_id)
