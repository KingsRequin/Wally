# tests/v2/core/memory/test_facts.py
"""Tests pour AtomicFact + SQLiteFactStore."""
import pytest
from datetime import datetime, timedelta

from bot.v2.core.memory.facts import (
    AtomicFact, FactCategory, FactStatus, FactRelation,
    DECAY_RATES, SQLiteFactStore,
)


def make_fact(user_id="discord:123", content="Kaelis aime le café",
              category=FactCategory.PREF, confidence=1.0) -> AtomicFact:
    return AtomicFact(user_id=user_id, content=content, category=category, confidence=confidence)


@pytest.mark.asyncio
async def test_add_fact_returns_id(tmp_db_path):
    """add() retourne un entier positif (l'ID SQLite)."""
    store = SQLiteFactStore(tmp_db_path)
    fact = make_fact()
    fact_id = await store.add(fact)
    assert isinstance(fact_id, int)
    assert fact_id > 0
    assert fact.id == fact_id


@pytest.mark.asyncio
async def test_get_by_user_returns_added_fact(tmp_db_path):
    """get_by_user() retourne le fait ajouté."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Aime le café noir"))
    facts = await store.get_by_user("discord:123")
    assert len(facts) == 1
    assert facts[0].content == "Aime le café noir"
    assert facts[0].category == FactCategory.PREF


@pytest.mark.asyncio
async def test_get_by_user_filters_by_min_confidence(tmp_db_path):
    """get_by_user() exclut les faits sous le seuil de confiance."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Haut", confidence=0.8))
    await store.add(make_fact(content="Bas", confidence=0.1))
    facts = await store.get_by_user("discord:123", min_confidence=0.5)
    assert len(facts) == 1
    assert facts[0].content == "Haut"


@pytest.mark.asyncio
async def test_get_by_user_filters_by_category(tmp_db_path):
    """get_by_user() filtre par catégorie si spécifié."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="Préférence", category=FactCategory.PREF))
    await store.add(make_fact(content="Fait biographique", category=FactCategory.FAIT))
    facts = await store.get_by_user("discord:123", categories=[FactCategory.FAIT])
    assert len(facts) == 1
    assert facts[0].category == FactCategory.FAIT


def test_decay_rates_match_spec():
    """Les decay_rates par défaut correspondent aux valeurs du spec."""
    assert DECAY_RATES[FactCategory.FAIT] == 0.001
    assert DECAY_RATES[FactCategory.DESIRE] == 0.02
    assert DECAY_RATES[FactCategory.THOUGHT] == 0.05
    # AtomicFact.__post_init__ assigne le bon decay_rate
    fact = make_fact(category=FactCategory.DESIRE)
    assert fact.decay_rate == 0.02


@pytest.mark.asyncio
async def test_apply_decay_reduces_confidence(tmp_db_path):
    """apply_decay() réduit la confiance des faits actifs."""
    store = SQLiteFactStore(tmp_db_path)
    fact = make_fact(confidence=0.5)
    await store.add(fact)
    count = await store.apply_decay()
    assert count >= 1
    facts = await store.get_by_user("discord:123", min_confidence=0.0)
    assert facts[0].confidence < 0.5


@pytest.mark.asyncio
async def test_supersede_marks_old_fact(tmp_db_path):
    """supersede() marque l'ancien fait comme superseded et crée la relation."""
    store = SQLiteFactStore(tmp_db_path)
    old_id = await store.add(make_fact(content="Ancien fait"))
    new_id = await store.add(make_fact(content="Nouveau fait"))
    await store.supersede(old_id, new_id)

    # L'ancien fait ne doit plus apparaître dans les résultats actifs
    active = await store.get_by_user("discord:123")
    contents = [f.content for f in active]
    assert "Ancien fait" not in contents
    assert "Nouveau fait" in contents


@pytest.mark.asyncio
async def test_apply_decay_archives_below_threshold(tmp_db_path):
    """apply_decay() archive les faits dont confidence tombe sous 0.1."""
    store = SQLiteFactStore(tmp_db_path)
    # confidence=0.11, decay_rate=THOUGHT=0.05 → résultat 0.06 < 0.1 → archived
    fact = AtomicFact(
        user_id="discord:123", content="pensée éphémère",
        category=FactCategory.THOUGHT, confidence=0.11,
    )
    await store.add(fact)
    await store.apply_decay()
    # Ne doit plus apparaître dans les résultats actifs
    facts = await store.get_by_user("discord:123", min_confidence=0.0)
    assert len(facts) == 0  # archivé, status != active


@pytest.mark.asyncio
async def test_mark_seen_updates_last_seen_at(tmp_db_path):
    """mark_seen() met à jour last_seen_at."""
    store = SQLiteFactStore(tmp_db_path)
    fact = AtomicFact(
        user_id="discord:123", content="test",
        category=FactCategory.PREF,
        created_at=datetime.utcnow() - timedelta(hours=1),
        last_seen_at=datetime.utcnow() - timedelta(hours=1),
    )
    fact_id = await store.add(fact)
    await store.mark_seen(fact_id)
    facts = await store.get_by_user("discord:123")
    # last_seen_at doit être plus récent que created_at
    assert facts[0].last_seen_at > facts[0].created_at


@pytest.mark.asyncio
async def test_delete_by_user_removes_only_that_user(tmp_db_path):
    """delete_by_user() supprime uniquement les faits d'un utilisateur."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(AtomicFact(user_id="discord:1", content="a", category=FactCategory.FAIT))
    await store.add(AtomicFact(user_id="discord:1", content="b", category=FactCategory.FAIT))
    await store.add(AtomicFact(user_id="discord:2", content="c", category=FactCategory.FAIT))

    deleted = await store.delete_by_user("discord:1")
    assert deleted == 2
    assert await store.count_by_user("discord:1") == 0
    assert await store.count_by_user("discord:2") == 1


@pytest.mark.asyncio
async def test_sample_random_returns_active_facts(tmp_db_path):
    """sample_random() renvoie uniquement des faits actifs, dans la limite."""
    store = SQLiteFactStore(tmp_db_path)
    for i in range(5):
        await store.add(make_fact(content=f"fait {i}", category=FactCategory.FAIT))
    sampled = await store.sample_random(limit=3)
    assert len(sampled) == 3
    assert all(f.status == FactStatus.ACTIVE for f in sampled)


@pytest.mark.asyncio
async def test_sample_random_excludes_category(tmp_db_path):
    """sample_random(exclude_category=THOUGHT) ne renvoie aucun THOUGHT."""
    store = SQLiteFactStore(tmp_db_path)
    await store.add(make_fact(content="souvenir", category=FactCategory.FAIT))
    await store.add(make_fact(content="pensée", category=FactCategory.THOUGHT))
    sampled = await store.sample_random(limit=10, exclude_category=FactCategory.THOUGHT)
    assert all(f.category != FactCategory.THOUGHT for f in sampled)
    assert any(f.category == FactCategory.FAIT for f in sampled)


@pytest.mark.asyncio
async def test_sample_random_empty_db(tmp_db_path):
    """sample_random() sur une base vide renvoie []."""
    store = SQLiteFactStore(tmp_db_path)
    assert await store.sample_random(limit=3) == []


@pytest.mark.asyncio
async def test_set_status_changes_status(tmp_db_path):
    """set_status() change le statut d'un fait (ex. GOAL → ARCHIVED)."""
    store = SQLiteFactStore(tmp_db_path)
    gid = await store.add(make_fact(content="un but", category=FactCategory.GOAL))
    await store.set_status(gid, FactStatus.ARCHIVED)
    active = await store.get_by_user("discord:123", categories=[FactCategory.GOAL])
    assert active == []  # plus actif
    archived = await store.get_by_user(
        "discord:123", categories=[FactCategory.GOAL], status=FactStatus.ARCHIVED
    )
    assert len(archived) == 1


@pytest.mark.asyncio
async def test_append_progress_adds_line(tmp_db_path):
    """append_progress() ajoute une ligne de progression sous un séparateur."""
    store = SQLiteFactStore(tmp_db_path)
    gid = await store.add(make_fact(content="Apprendre les goûts musicaux", category=FactCategory.GOAL))
    assert await store.append_progress(gid, "demandé à Kaelis") is True
    facts = await store.get_by_user("discord:123", categories=[FactCategory.GOAL])
    content = facts[0].content
    assert "Apprendre les goûts musicaux" in content  # intitulé conservé
    assert "— progression —" in content
    assert "· demandé à Kaelis" in content


@pytest.mark.asyncio
async def test_append_progress_caps_oldest_dropped(tmp_db_path):
    """append_progress() cap à max_step_lines : les plus vieilles étapes tombent,
    l'intitulé reste."""
    store = SQLiteFactStore(tmp_db_path)
    gid = await store.add(make_fact(content="Le but initial", category=FactCategory.GOAL))
    for i in range(5):
        await store.append_progress(gid, f"etape{i}", max_step_lines=3)
    facts = await store.get_by_user("discord:123", categories=[FactCategory.GOAL])
    content = facts[0].content
    assert "Le but initial" in content       # intitulé conservé
    assert "etape0" not in content           # plus vieilles jetées
    assert "etape1" not in content
    assert "etape2" in content
    assert "etape3" in content
    assert "etape4" in content


@pytest.mark.asyncio
async def test_append_progress_updates_last_seen(tmp_db_path):
    """append_progress() met à jour last_seen_at."""
    store = SQLiteFactStore(tmp_db_path)
    fact = AtomicFact(
        user_id="discord:123", content="but",
        category=FactCategory.GOAL,
        created_at=datetime.utcnow() - timedelta(hours=1),
        last_seen_at=datetime.utcnow() - timedelta(hours=1),
    )
    gid = await store.add(fact)
    await store.append_progress(gid, "un pas")
    facts = await store.get_by_user("discord:123", categories=[FactCategory.GOAL])
    assert facts[0].last_seen_at > facts[0].created_at


@pytest.mark.asyncio
async def test_append_progress_returns_false_if_missing(tmp_db_path):
    """append_progress() retourne False si le but n'existe pas."""
    store = SQLiteFactStore(tmp_db_path)
    assert await store.append_progress(99999, "un pas") is False


@pytest.mark.asyncio
async def test_append_progress_returns_false_if_inactive(tmp_db_path):
    """append_progress() retourne False si le but n'est pas actif."""
    store = SQLiteFactStore(tmp_db_path)
    gid = await store.add(make_fact(content="but archivé", category=FactCategory.GOAL))
    await store.set_status(gid, FactStatus.ARCHIVED)
    assert await store.append_progress(gid, "un pas") is False
