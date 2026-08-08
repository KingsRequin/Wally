"""Le panneau Mémoire redevient utilisable : ajouter, corriger, supprimer.

Ces routes répondaient `501 Mémoire en refonte — indisponible` depuis la
migration V2 : neutralisées avec le store V1, jamais rebranchées sur
`SQLiteFactStore` qui a pourtant tout ce qu'il faut. Les boutons étaient là et ne
faisaient rien.

Une suppression ARCHIVE plutôt qu'elle n'efface : `get_by_user` ne rend que les
faits actifs, le souvenir disparaît donc de l'écran, mais reste traçable — une
mémoire supprimée par erreur n'est pas perdue.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.dashboard.routes.memory import router


def _client(store):
    app = FastAPI()
    app.include_router(router)
    wally = MagicMock()
    wally.fact_store = store
    app.state.wally = wally
    return TestClient(app)


def _store():
    store = MagicMock()
    store.add = AsyncMock(return_value=7)
    store.set_status = AsyncMock()
    store.update_content = AsyncMock(return_value=True)
    store.delete_by_user = AsyncMock(return_value=3)
    return store


def test_ajouter_un_souvenir():
    store = _store()
    r = _client(store).post("/memory/users/discord:1/memories",
                            json={"content": "aime le jazz", "category": "PREF"})

    assert r.status_code == 200
    fact = store.add.await_args.args[0]
    assert fact.user_id == "discord:1"
    assert fact.content == "aime le jazz"
    assert fact.category.value == "PREF"


def test_une_categorie_inconnue_retombe_sur_fait():
    """L'UI envoie parfois une chaîne vide : ne pas planter pour ça."""
    store = _store()
    r = _client(store).post("/memory/users/discord:1/memories",
                            json={"content": "quelque chose", "category": ""})

    assert r.status_code == 200
    assert store.add.await_args.args[0].category.value == "FAIT"


def test_un_contenu_vide_est_refuse():
    store = _store()
    r = _client(store).post("/memory/users/discord:1/memories",
                            json={"content": "   ", "category": "FAIT"})

    assert r.status_code == 400
    store.add.assert_not_awaited()


def test_corriger_un_souvenir():
    store = _store()
    r = _client(store).put("/memory/users/discord:1/memories/7",
                           json={"content": "aime le blues"})

    assert r.status_code == 200
    store.update_content.assert_awaited_once_with(7, "aime le blues")


def test_corriger_un_souvenir_inexistant_donne_404():
    store = _store()
    store.update_content = AsyncMock(return_value=False)
    r = _client(store).put("/memory/users/discord:1/memories/999",
                           json={"content": "peu importe"})

    assert r.status_code == 404


def test_supprimer_un_souvenir_larchive():
    """Il disparaît de l'écran sans disparaître de la base."""
    from bot.intelligence.memory.facts import FactStatus

    store = _store()
    r = _client(store).delete("/memory/users/discord:1/memories/7")

    assert r.status_code == 200
    store.set_status.assert_awaited_once_with(7, FactStatus.ARCHIVED)


def test_supprimer_un_utilisateur_efface_ses_faits():
    store = _store()
    r = _client(store).delete("/memory/users/discord:1")

    assert r.status_code == 200
    assert r.json()["deleted"] == 3
    store.delete_by_user.assert_awaited_once_with("discord:1")


def test_sans_store_les_routes_repondent_503():
    """Mieux qu'un 500 : la mémoire n'est pas là, ce n'est pas une erreur de
    l'appelant."""
    client = _client(None)
    assert client.delete("/memory/users/discord:1/memories/7").status_code == 503
    assert client.post("/memory/users/discord:1/memories",
                       json={"content": "x"}).status_code == 503


# ── sur une vraie base, pas seulement des mocks ──

@pytest.fixture
async def store_reel(tmp_path):
    from bot.db.schema_v2 import create_v2_tables
    from bot.intelligence.memory.facts import SQLiteFactStore

    path = str(tmp_path / "facts.db")
    await create_v2_tables(path)
    return SQLiteFactStore(path)


@pytest.mark.asyncio
async def test_corriger_puis_archiver_sur_une_vraie_base(store_reel):
    from bot.intelligence.memory.facts import AtomicFact, FactCategory, FactStatus

    fid = await store_reel.add(AtomicFact(
        user_id="discord:1", content="aime le jazz", category=FactCategory.PREF,
        subject="pierre", predicate="aime", object_="le jazz",
    ))

    assert await store_reel.update_content(fid, "aime le blues") is True
    faits = await store_reel.get_by_user("discord:1")
    assert faits[0].content == "aime le blues"
    assert faits[0].predicate == "aime"      # le triplet d'origine est conservé

    await store_reel.set_status(fid, FactStatus.ARCHIVED)
    assert await store_reel.get_by_user("discord:1") == []   # hors de vue…
    assert await store_reel.count_by_user("discord:1") == 1  # …mais pas perdu


@pytest.mark.asyncio
async def test_corriger_un_id_absent_rend_false(store_reel):
    assert await store_reel.update_content(999, "peu importe") is False
