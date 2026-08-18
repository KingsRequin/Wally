"""L'extension se télécharge depuis le bot, toujours à jour.

Azraël n'a pas de compte sur ce dashboard et n'a pas accès au dépôt : il lui faut
une URL. Le zip est donc construit À LA VOLÉE depuis `extension-musique/` plutôt
que déposé une fois pour toutes — un fichier figé se périme à la première
correction, et on envoie alors une vieille version sans le savoir.

La garde qui compte : **aucun secret ne doit sortir dans ce zip**. La route est
publique par nécessité (Azraël doit pouvoir la charger), donc le jour où
quelqu'un écrira un jeton en dur dans l'extension « pour simplifier
l'installation », ce test doit hurler.
"""
import io
import zipfile
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from bot.dashboard.routes.music import public_router

    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    app.state.wally = MagicMock()
    return TestClient(app)


def _zip(client):
    r = client.get("/api/public/extension-musique.zip")
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_le_zip_contient_l_extension_complete(client):
    """Un manifeste sans ses scripts donne une extension qui refuse de se
    charger, avec un message que personne ne sait lire."""
    noms = set(_zip(client).namelist())
    assert {"manifest.json", "lib.js", "pont.js", "content.js",
            "popup.html", "popup.js", "README.md"} <= noms


def test_le_zip_ne_contient_AUCUN_secret(client):
    """La route est publique — Azraël doit pouvoir la charger sans compte. Le
    jour où un jeton est écrit en dur dans l'extension « pour simplifier
    l'installation », il partirait à tout internet."""
    z = _zip(client)
    for nom in z.namelist():
        contenu = z.read(nom).decode("utf-8", "replace").lower()
        assert "music_extension_token" not in contenu
        # Le jeton réel fait 48 caractères hexadécimaux : aucune chaîne de cette
        # forme n'a de raison d'être dans l'extension.
        import re
        assert not re.search(r"\b[0-9a-f]{40,}\b", contenu), nom


def test_le_zip_se_TELECHARGE_sous_un_nom_lisible(client):
    """Il atterrit dans les téléchargements d'Azraël : « response.zip » ne lui
    dirait rien trois jours plus tard."""
    r = client.get("/api/public/extension-musique.zip")
    disposition = r.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert ".zip" in disposition


def test_le_zip_est_reconstruit_a_chaque_appel(client):
    """C'est tout l'intérêt : après une correction de l'extension, l'URL sert la
    version corrigée sans rien redéployer d'autre."""
    import inspect

    from bot.dashboard.routes import music

    source = inspect.getsource(music.telecharger_extension)
    assert "ZipFile" in source
