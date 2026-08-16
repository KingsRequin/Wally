"""Les routes de mise en scène de l'overlay, à l'aveugle du code qui les sert.

Patron du dépôt : `FastAPI()` monté à la main, `app.state.wally = MagicMock()`
(`tests/test_dashboard_emotion_api.py`). La base est un faux `_State` avec
`get_state`/`set_state` asynchrones, repris de `tests/test_overlay_layout_store.py` —
un `MagicMock` en guise de base rendrait `charger_layout`/`enregistrer_layout`
non représentatifs de ce qui se passe en vrai (ils appelleraient une méthode
mockée qui ne range ni ne relit rien).
"""
import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.core.overlay_layout import layout_par_defaut
from bot.core.overlay_layout_store import LAYOUT_KEY
from bot.dashboard.routes.overlay import admin_router, public_router


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


def _client(db):
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    app.include_router(admin_router, prefix="/api/admin")
    app.state.wally = MagicMock()
    app.state.wally.db = db
    return TestClient(app)


# ── route publique ──

def test_get_layout_sans_scene_rend_la_scene_par_defaut():
    client = _client(_State())
    r = client.get("/api/public/overlay-layout")
    assert r.status_code == 200
    data = r.json()
    assert data["defaut"] == "en-jeu"
    assert data["scene"]["slug"] == "en-jeu"


def test_get_layout_avec_une_scene_precise():
    client = _client(_State())
    r = client.get("/api/public/overlay-layout", params={"scene": "stream-starting"})
    assert r.status_code == 200
    assert r.json()["scene"]["slug"] == "stream-starting"


def test_scene_inexistante_sert_le_defaut_jamais_un_404():
    """OBS peut pointer sur une scène supprimée entre-temps : un 404 laisserait
    l'écran noir en plein live. NE PAS remplacer ce 200 par un 404."""
    client = _client(_State())
    r = client.get("/api/public/overlay-layout", params={"scene": "fantome"})
    assert r.status_code == 200
    assert r.json()["scene"]["slug"] == "en-jeu"


def test_get_layout_repond_meme_sans_base_connectee():
    """La page est servie avant que le bot soit connecté : `db` est `None`."""
    client = _client(None)
    r = client.get("/api/public/overlay-layout")
    assert r.status_code == 200
    assert r.json()["scene"]["slug"] == "en-jeu"


# ── route admin : lecture ──

def test_get_admin_layout_rend_le_modele_entier():
    client = _client(_State())
    r = client.get("/api/admin/overlay/layout")
    assert r.status_code == 200
    data = r.json()
    assert {s["slug"] for s in data["scenes"]} == {"stream-starting", "en-jeu", "fin"}


def test_get_admin_layout_joint_les_libelles_lisibles():
    """Les noms français des éléments voyagent AVEC le layout : le panneau fait
    déjà cet appel au chargement, et un second aller-retour pour trente-quatre
    chaînes constantes ne se justifie pas. Sans eux, le streamer relit
    « apex_predator » au lieu de « Seuil Prédateur »."""
    client = _client(_State())
    r = client.get("/api/admin/overlay/layout")
    assert r.status_code == 200
    libelles = r.json()["libelles"]
    assert libelles["apex_predator"]["nom"] == "Seuil Prédateur"
    assert libelles["apex_predator"]["description"].strip()
    # Tout élément réglable doit être nommable, sinon la liste affiche des clés.
    manquants = set(layout_par_defaut()["scenes"][0]["elements"]) - set(libelles)
    assert not manquants, f"sans libellé : {sorted(manquants)}"


def test_get_admin_layout_defauts_sert_la_livraison_sans_rien_ecrire():
    """« Réinitialiser » lit les valeurs d'origine ICI, et nulle part ailleurs.

    Deux tables de défauts — une en Python, une dans le navigateur — auraient
    divergé à la première évolution du modèle, et « remettre à l'origine »
    aurait rendu une position qui n'est plus celle d'origine. La route les sert
    donc, et elle ne touche pas à ce qui est rangé.
    """
    db = _State()
    # Une mise en scène déjà réglée, en base : c'est elle que le GET normal rend.
    range_ = layout_par_defaut()
    range_["scenes"][0]["elements"]["bingo"]["x"] = 12.5
    db.rows[LAYOUT_KEY] = json.dumps(range_)
    client = _client(db)

    servi = client.get("/api/admin/overlay/layout", params={"defauts": 1})
    assert servi.status_code == 200
    origine = layout_par_defaut()["scenes"][0]["elements"]["bingo"]
    assert servi.json()["scenes"][0]["elements"]["bingo"] == origine
    # Les libellés voyagent aussi : le panneau lit la réponse avec le même code.
    assert servi.json()["libelles"]["bingo"]["nom"]

    # Rien n'a bougé en base, et le GET normal rend toujours le réglé.
    assert json.loads(db.rows[LAYOUT_KEY])["scenes"][0]["elements"]["bingo"]["x"] == 12.5
    normal = client.get("/api/admin/overlay/layout")
    assert normal.json()["scenes"][0]["elements"]["bingo"]["x"] == 12.5


def test_get_admin_layout_sans_defauts_rend_ce_qui_est_range():
    """Le paramètre absent ne change RIEN : c'est le chemin de tous les jours."""
    db = _State()
    range_ = layout_par_defaut()
    range_["scenes"][0]["elements"]["avatar"]["scale"] = 1.4
    db.rows[LAYOUT_KEY] = json.dumps(range_)
    r = _client(db).get("/api/admin/overlay/layout", params={"defauts": 0})
    assert r.json()["scenes"][0]["elements"]["avatar"]["scale"] == 1.4


# ── route admin : écriture ──

def test_put_borne_la_position_avant_de_ranger():
    """La validation passe AVANT l'écriture : la valeur rendue ET la valeur
    rangée en base doivent être bornées, sinon la valeur aberrante resterait
    servie jusqu'au prochain enregistrement."""
    db = _State()
    client = _client(db)
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 5000.0

    r = client.put("/api/admin/overlay/layout", json=layout)

    assert r.status_code == 200
    assert r.json()["scenes"][0]["elements"]["avatar"]["x"] == 100.0
    range_en_base = json.loads(db.rows[LAYOUT_KEY])
    assert range_en_base["scenes"][0]["elements"]["avatar"]["x"] == 100.0


def test_put_publie_un_signal_nu_sans_le_layout():
    """`OverlayFeed.recent()` rejoue les dix derniers événements à chaque
    connexion : y pousser le modèle entier chasserait des bulles utiles du
    tampon. L'événement doit rester EXACTEMENT ce signal, sans clé `layout`."""
    client = _client(_State())

    client.put("/api/admin/overlay/layout", json=layout_par_defaut())

    client.app.state.wally.overlay_feed.publish.assert_called_once_with(
        {"type": "layout", "scene": None}
    )


def test_put_json_invalide_rend_400():
    client = _client(_State())
    r = client.put("/api/admin/overlay/layout", content=b"{ceci n'est pas du json")
    assert r.status_code == 400
