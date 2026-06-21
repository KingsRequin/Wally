"""Phase 2 du port mémoire jarvis-OS : ingest + réconciliation 2 étages.

Tous les tests utilisent un FAUX LLM (`FakeLLM`) — aucun appel réseau. Le faux
LLM renvoie un JSON scripté en fonction du contenu du prompt (extraction vs
arbitrage). On vérifie l'anti-doublon (confirm), la supersession, le
needs_review hors-vocab, l'étage 2 FTS, et le cas extraction vide.
"""
from __future__ import annotations

import json

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.memory.facts import (
    AtomicFact, FactCategory, FactStatus, SQLiteFactStore, _normalize,
)
from bot.intelligence.memory.ingest import MemoryIngest, IngestResult, _Candidate


# ── Faux LLM ──────────────────────────────────────────────────────────────────


class FakeLLM:
    """LLM scripté. Distingue extraction (prompt d'extraction) d'arbitrage
    (prompt arbitre) via un marqueur textuel, et renvoie un JSON préprogrammé.

    `extract_payload` : dict {"facts": [...]} renvoyé pour l'extraction.
    `arbiter_payload` : dict {"verdict":..., "target_fact_id":...} pour l'arbitre.
    """

    def __init__(self, extract_payload: dict | None = None,
                 arbiter_payload: dict | None = None) -> None:
        self.extract_payload = extract_payload if extract_payload is not None else {"facts": []}
        self.arbiter_payload = arbiter_payload or {"verdict": "new", "target_fact_id": None}
        self.calls: list[str] = []

    async def complete(self, system_prompt: str, messages: list[dict],
                       *args, **kwargs) -> str:
        user = messages[-1]["content"] if messages else ""
        blob = (system_prompt or "") + " " + user
        if "verdict" in blob.lower() or "arbitre" in blob.lower():
            self.calls.append("arbiter")
            return json.dumps(self.arbiter_payload)
        self.calls.append("extract")
        return json.dumps(self.extract_payload)


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "wally_ingest.db")
    await create_v2_tables(db_path)
    return SQLiteFactStore(db_path)


def _one_fact(subject="KingsRequin", predicate="plays", object_="Apex",
              category="FAIT", confidence_source="explicit", importance=0.6):
    return {"facts": [{
        "subject": subject, "predicate": predicate, "object": object_,
        "category": category, "confidence_source": confidence_source,
        "importance": importance,
    }]}


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_creates_new_fact_with_spo(store):
    llm = FakeLLM(extract_payload=_one_fact())
    ingest = MemoryIngest(store, llm)
    result = await ingest.ingest("discord:1", "KingsRequin joue à Apex.")

    assert isinstance(result, IngestResult)
    assert result.raw_extracted_count == 1
    assert len(result.new_facts) == 1
    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1
    f = facts[0]
    assert f.subject == "KingsRequin"
    assert f.predicate == "plays"
    assert f.object_ == "Apex"
    assert f.category is FactCategory.FAIT


@pytest.mark.asyncio
async def test_same_fact_twice_confirms_no_duplicate(store):
    """LE test clé : même fait ingéré 2× → 1 seul fait, support_count=2."""
    llm = FakeLLM(extract_payload=_one_fact())
    ingest = MemoryIngest(store, llm)

    r1 = await ingest.ingest("discord:1", "KingsRequin joue à Apex.")
    assert len(r1.new_facts) == 1

    r2 = await ingest.ingest("discord:1", "KingsRequin joue encore à Apex.")
    assert len(r2.confirmed) == 1
    assert len(r2.new_facts) == 0

    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1  # PAS de doublon
    assert facts[0].support_count == 2


@pytest.mark.asyncio
async def test_stable_contradiction_supersedes(store):
    """Catégorie stable, object contradictoire, arbitre 'contradicts' → supersede."""
    # 1er fait : GOAL (stable)
    llm1 = FakeLLM(extract_payload=_one_fact(
        subject="KingsRequin", predicate="wants", object_="sub-3h marathon",
        category="GOAL"))
    ingest1 = MemoryIngest(store, llm1)
    await ingest1.ingest("discord:1", "KingsRequin vise un marathon en moins de 3h.")

    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1
    old_id = facts[0].id

    # 2e fait : même subject+predicate+category, object différent → arbitre contradicts
    llm2 = FakeLLM(
        extract_payload=_one_fact(
            subject="KingsRequin", predicate="wants", object_="3h10 marathon",
            category="GOAL"),
        arbiter_payload={"verdict": "contradicts", "target_fact_id": old_id},
    )
    ingest2 = MemoryIngest(store, llm2)
    r2 = await ingest2.ingest("discord:1", "Finalement KingsRequin vise 3h10.")

    assert len(r2.superseded_pairs) == 1
    assert "arbiter" in llm2.calls

    active = await store.get_by_user("discord:1", status=FactStatus.ACTIVE)
    assert len(active) == 1
    assert active[0].object_ == "3h10 marathon"
    superseded = await store.get_by_user("discord:1", status=FactStatus.SUPERSEDED)
    assert len(superseded) == 1
    assert superseded[0].id == old_id


@pytest.mark.asyncio
async def test_out_of_vocab_predicate_needs_review(store):
    llm = FakeLLM(extract_payload=_one_fact(predicate="frobnicates"))
    ingest = MemoryIngest(store, llm)
    result = await ingest.ingest("discord:1", "blah")

    assert len(result.needs_review) == 1
    assert len(result.new_facts) == 0
    review = await store.get_by_user(
        "discord:1", status=FactStatus.NEEDS_REVIEW, min_confidence=0.0)
    assert len(review) == 1
    assert review[0].predicate == "frobnicates"


@pytest.mark.asyncio
async def test_out_of_vocab_category_needs_review(store):
    llm = FakeLLM(extract_payload=_one_fact(category="WEATHER"))
    ingest = MemoryIngest(store, llm)
    result = await ingest.ingest("discord:1", "blah")
    assert len(result.needs_review) == 1


@pytest.mark.asyncio
async def test_stage2_sibling_same_as_confirms(store):
    """Étage 2 : pas de match exact (prédicat différent) mais sibling trouvé via
    FTS, arbitre 'same_as' → confirm le sibling, pas de doublon."""
    # Fait existant : "uses" Neovim
    seed = AtomicFact(
        user_id="discord:1", content="Kaelis uses Neovim",
        category=FactCategory.FAIT, subject="Kaelis", predicate="uses",
        object_="Neovim", confidence=0.7)
    sib_id = await store.add(seed)

    # Candidat : prédicat différent ("prefers") → pas de match exact étage 1.
    # Object recouvre "Neovim" → sibling trouvé via FTS. Arbitre = same_as.
    llm = FakeLLM(
        extract_payload=_one_fact(
            subject="Kaelis", predicate="prefers", object_="Neovim",
            category="FAIT"),
        arbiter_payload={"verdict": "same_as", "target_fact_id": sib_id},
    )
    ingest = MemoryIngest(store, llm)
    result = await ingest.ingest("discord:1", "Kaelis ne jure que par Neovim.")

    assert len(result.confirmed) == 1
    assert "arbiter" in llm.calls
    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1  # pas de doublon
    assert facts[0].id == sib_id
    assert facts[0].support_count == 2


@pytest.mark.asyncio
async def test_empty_extraction_yields_no_facts(store):
    llm = FakeLLM(extract_payload={"facts": []})
    ingest = MemoryIngest(store, llm)
    result = await ingest.ingest("discord:1", "salut ça va ?")

    assert result.raw_extracted_count == 0
    assert result.new_facts == []
    assert result.confirmed == []
    assert await store.get_by_user("discord:1") == []


@pytest.mark.asyncio
async def test_volatile_category_coexists_no_arbiter(store):
    """Catégorie volatile (PREF) : object différent sur même S-P-cat → coexiste
    sans appeler l'arbitre."""
    llm1 = FakeLLM(extract_payload=_one_fact(
        predicate="prefers", object_="café", category="PREF"))
    ingest1 = MemoryIngest(store, llm1)
    await ingest1.ingest("discord:1", "KingsRequin préfère le café.")

    llm2 = FakeLLM(extract_payload=_one_fact(
        predicate="prefers", object_="thé", category="PREF"))
    ingest2 = MemoryIngest(store, llm2)
    r2 = await ingest2.ingest("discord:1", "KingsRequin aime aussi le thé.")

    assert len(r2.new_facts) == 1
    assert "arbiter" not in llm2.calls  # pas d'arbitrage sur catégorie volatile
    facts = await store.get_by_user("discord:1")
    assert len(facts) == 2


@pytest.mark.asyncio
async def test_reconcile_candidate_new_then_confirm(store):
    """reconcile_candidate sur un candidat pré-construit : 1er appel → new,
    2e appel (même S-P-O) → confirmed, sans extraction LLM."""
    llm = FakeLLM()  # extraction non utilisée ici
    ingest = MemoryIngest(store, llm)

    cand = _Candidate(
        subject="KingsRequin", predicate="plays", object="Apex",
        category="FAIT", confidence_source="explicit", importance=0.6,
    )
    kind1, fact1 = await ingest.reconcile_candidate("discord:1", cand)
    assert kind1 == "new"
    assert "extract" not in llm.calls  # aucune extraction déclenchée

    kind2, fact2 = await ingest.reconcile_candidate("discord:1", cand)
    assert kind2 == "confirmed"

    facts = await store.get_by_user("discord:1")
    assert len(facts) == 1  # pas de doublon
    assert facts[0].support_count == 2


def test_normalize_helper():
    assert _normalize("  Café   Noir!! ") == "café noir"
    assert _normalize("sub-3h marathon") == "sub3h marathon"
    assert _normalize("") == ""
