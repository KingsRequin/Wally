"""Phase 8 : faits périmés lus, alias perdu au reboot, écritures concurrentes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore
from bot.intelligence.memory.service import MemoryService


@pytest.fixture
async def store(tmp_path):
    chemin = str(tmp_path / "facts.db")
    await create_v2_tables(chemin)
    return SQLiteFactStore(chemin)


async def _ajouter(store, uid, contenu, expires_at=None, categorie=FactCategory.FAIT):
    return await store.add(AtomicFact(
        user_id=uid, content=contenu, category=categorie, expires_at=expires_at,
    ))


# ── Un fait périmé ne remonte plus, quel que soit le chemin ──────────────────
#
# Seuls `search_fts` et `search_related` portaient le filtre. Or l'archivage des
# périmés est QUOTIDIEN : un fait éphémère restait `active` jusqu'à ~24 h après
# sa date. Le repli de `MemoryRetrieval.search` — quand la FTS ne rend rien —
# passe justement par `get_by_user`, et `service.py` documentait le contraire.

async def test_get_by_user_ecarte_un_fait_perime(store):
    passe = datetime.utcnow() - timedelta(hours=2)
    futur = datetime.utcnow() + timedelta(days=1)
    await _ajouter(store, "discord:610", "va au ciné ce soir", expires_at=passe)
    await _ajouter(store, "discord:610", "part en vacances demain", expires_at=futur)
    await _ajouter(store, "discord:610", "habite à Lyon")

    contenus = {f.content for f in await store.get_by_user("discord:610")}

    assert "va au ciné ce soir" not in contenus
    assert contenus == {"part en vacances demain", "habite à Lyon"}


async def test_sample_random_ecarte_un_fait_perime(store):
    passe = datetime.utcnow() - timedelta(hours=2)
    await _ajouter(store, "discord:610", "intention caduque", expires_at=passe)

    assert await store.sample_random(limit=10) == []


async def test_search_by_category_ecarte_un_fait_perime(store):
    passe = datetime.utcnow() - timedelta(hours=2)
    await _ajouter(store, "discord:610", "but caduc",
                   expires_at=passe, categorie=FactCategory.GOAL)

    assert await store.search_by_category(FactCategory.GOAL) == []


# ── Le busy_timeout s'applique aux connexions ad-hoc ─────────────────────────

def test_le_store_pose_son_propre_busy_timeout():
    """`busy_timeout` est un réglage DE CONNEXION : contrairement à WAL, il ne se
    propage pas depuis la connexion principale. Le commentaire de `database.py`
    affirmait le contraire et aurait envoyé le prochain diagnostic
    « database is locked » sur une fausse piste."""
    import inspect

    assert SQLiteFactStore.BUSY_TIMEOUT_S >= 10.0
    source = inspect.getsource(SQLiteFactStore._connect)
    assert "timeout=self.BUSY_TIMEOUT_S" in source
    # Plus aucune connexion nue dans le module.
    module = inspect.getsource(SQLiteFactStore)
    assert "aiosqlite.connect(self._db_path)" not in module


# ── Le routage d'un pseudo survit au redémarrage ─────────────────────────────

async def test_load_aliases_indexe_les_deux_conventions():
    """`fact_extractor` posait `unknown:<pseudo>` à la volée, seule
    `nickname:<pseudo>` était persistée. Or `unknown:` est la SEULE forme
    atteignable depuis `_user_id()`, qui compose `f"{platform}:{user_id}"` : le
    routage marchait donc jusqu'au reboot, puis cessait en silence."""
    memory = MemoryService(config=MagicMock())
    db = MagicMock()
    db.get_alias_map = AsyncMock(return_value={})
    db.get_nickname_alias_map = AsyncMock(return_value={"azrael": "discord:610"})

    await memory.load_aliases(db)

    assert memory._alias_cache["nickname:azrael"] == "discord:610"
    assert memory._alias_cache["unknown:azrael"] == "discord:610"
    # Et le routage effectif suit.
    assert memory._user_id("unknown", "azrael") == "discord:610"


# ── Deux écritures concurrentes ne créent plus de doublon ────────────────────

async def test_deux_ajouts_simultanes_du_meme_fait_nen_ecrivent_quun(tmp_path):
    """Lecture puis écriture sur deux connexions distinctes, sans transaction
    commune ni contrainte d'unicité : Discord, Twitch et la boucle cognitive
    écrivant en parallèle, les deux passaient le test de doublon."""
    chemin = str(tmp_path / "facts.db")
    await create_v2_tables(chemin)
    memory = MemoryService(config=MagicMock())
    memory.set_embedding_backend(chemin)

    await asyncio.gather(
        memory.add("discord", "610550333042589752", "aime le jazz"),
        memory.add("discord", "610550333042589752", "aime le jazz"),
    )

    faits = await memory.fact_store.get_by_user("discord:610550333042589752")
    assert len(faits) == 1
    assert faits[0].support_count == 2      # le second a CONFIRMÉ le premier


async def test_deux_utilisateurs_ecrivent_toujours_en_parallele(tmp_path):
    """Le verrou est par `uid` : il ne doit pas sérialiser tout le monde."""
    chemin = str(tmp_path / "facts.db")
    await create_v2_tables(chemin)
    memory = MemoryService(config=MagicMock())
    memory.set_embedding_backend(chemin)

    await asyncio.gather(
        memory.add("discord", "610550333042589752", "aime le jazz"),
        memory.add("discord", "611550333042589753", "aime le rock"),
    )

    assert len(await memory.fact_store.get_by_user("discord:610550333042589752")) == 1
    assert len(await memory.fact_store.get_by_user("discord:611550333042589753")) == 1
