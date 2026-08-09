"""Le decay de la mémoire doit être APPELÉ, pas seulement implémenté.

`SQLiteFactStore.apply_decay()` existait depuis l'origine, `DECAY_RATES` calibrait
un taux par catégorie, la colonne `decay_rate` était écrite en base à chaque
insertion — et rien n'appelait la méthode. Seuls ses propres tests unitaires le
faisaient, ce qui donnait l'illusion d'un mécanisme vivant.

Preuve relevée le 2026-08-09 : les désirs créés le 2026-06-22, 47 jours plus tôt,
avaient encore `confidence = 1.0` avec `decay_rate = 0.02` en base. Après 47 nuits
de decay ils seraient à 0.06, donc archivés depuis longtemps. Le mécanisme n'avait
jamais tourné une seule fois.

D'où ce fichier : il teste le BRANCHEMENT (l'appel depuis la passe de maintenance),
là où les tests existants ne testaient que la méthode.
"""
from datetime import datetime, timezone

import pytest

from bot.intelligence.memory.facts import (
    AtomicFact,
    FactCategory,
    FactStatus,
    SQLiteFactStore,
)


async def _store(tmp_path) -> tuple[SQLiteFactStore, str]:
    from bot.db.schema_v2 import create_v2_tables

    chemin = str(tmp_path / "m.db")
    await create_v2_tables(chemin)
    return SQLiteFactStore(chemin), chemin


async def _ajouter(store, contenu, categorie, confiance):
    now = datetime.now(timezone.utc)
    fait = AtomicFact(user_id="wally:self", content=contenu, category=categorie,
                      confidence=confiance, created_at=now, last_seen_at=now)
    return await store.add(fait)


async def _etat(chemin, fid) -> tuple[str, float]:
    """Statut et confiance lus en SQL direct.

    `get_by_ids` filtre `confidence >= 0.3` et `status='active'` : un fait en fin de
    vie — exactement ce qu'on observe ici — y est invisible.
    """
    import aiosqlite

    async with aiosqlite.connect(chemin) as db:
        cur = await db.execute("SELECT status, confidence FROM atomic_facts WHERE id = ?", (fid,))
        row = await cur.fetchone()
    return row[0], row[1]


@pytest.mark.asyncio
async def test_la_maintenance_nocturne_applique_le_decay(tmp_path):
    """Le cron `memory_cleanup` doit user la confiance, pas seulement les périmés."""
    from bot.intelligence.memory.service import MemoryService

    store, chemin = await _store(tmp_path)
    # 0.12 de confiance, decay THOUGHT à 0.05 → sous le plancher de 0.1 en une nuit.
    pensee = await _ajouter(store, "une pensée en fin de vie", FactCategory.THOUGHT, 0.12)

    service = MemoryService.__new__(MemoryService)
    service._facts = store
    await service.cleanup_expired_facts()

    statut, _ = await _etat(chemin, pensee)
    assert statut == FactStatus.ARCHIVED.value, (
        "la passe de maintenance n'applique pas le decay — c'est le code mort du 2026-08-09"
    )


@pytest.mark.asyncio
async def test_le_decay_epargne_ce_quil_sait_des_gens(tmp_path):
    """FAIT à 0.001/nuit : 900 nuits de durée de vie. Une passe ne doit rien coûter.

    C'est la garantie qui rend le branchement acceptable : ce qu'il sait des
    personnes ne bouge pas, seules les pensées et les désirs s'effacent.
    """
    from bot.intelligence.memory.service import MemoryService

    store, chemin = await _store(tmp_path)
    fait = await _ajouter(store, "KingsRequin est mon créateur", FactCategory.FAIT, 1.0)

    service = MemoryService.__new__(MemoryService)
    service._facts = store
    await service.cleanup_expired_facts()

    statut, confiance = await _etat(chemin, fait)
    assert statut == FactStatus.ACTIVE.value
    assert confiance == pytest.approx(0.999)
