# tests/test_admin_prompts_filename_regex.py
r"""Les garde-fous de nom de fichier des routes `/api/admin/prompts/...`.

`re.match(..., filename)` avec un `$` non ancré accepte un saut de ligne
final en Python : `SOUL.md\n` (encodé `%0A` dans l'URL) passait la validation
alors que l'intention du garde-fou est de n'accepter que le format
`^[A-Z_]+\.md$` (persona) ou `^[\w_-]+\.md$` (system). Un fichier dont le nom
contient un saut de ligne aurait été créé.
"""
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from bot.dashboard.app import create_dashboard_app
from tests.test_dashboard_routes import _make_state

ADMIN_HEADERS = {"Authorization": "Bearer testtoken"}


@pytest.fixture
def app():
    return create_dashboard_app(_make_state())


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _pas_de_vraie_ecriture(monkeypatch):
    """Ces routes écrivent sous `bot/persona/` à un chemin calculé depuis
    `__file__`, pas injecté — donc pas substituable par un répertoire
    temporaire. On neutralise l'écriture réelle pour ne pas polluer le dépôt
    pendant les tests, quel que soit le verdict du garde-fou.
    """
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: None)
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)


@pytest.mark.parametrize("segment,nom_valide", [
    ("persona", "SOUL.md"),
    ("system", "reminder.md"),
])
async def test_un_saut_de_ligne_final_est_rejete(client, segment, nom_valide):
    resp = await client.post(
        f"/api/admin/prompts/{segment}/{nom_valide}%0A",
        json={"content": "x"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("segment,nom_valide", [
    ("persona", "SOUL.md"),
    ("system", "reminder.md"),
])
async def test_un_nom_valide_passe_toujours(client, segment, nom_valide):
    """Le garde-fou ne doit pas manger les noms valables."""
    resp = await client.post(
        f"/api/admin/prompts/{segment}/{nom_valide}",
        json={"content": "x"},
        headers=ADMIN_HEADERS,
    )
    assert resp.status_code == 200
