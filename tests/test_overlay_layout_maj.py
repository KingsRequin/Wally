"""Quand la mise en scène est partie à l'antenne pour la dernière fois.

Le pied de publication annonce « l'antenne diffuse toujours la version de
21:14 ». Sans date rangée, il n'aurait eu que deux choix : se taire, ou inventer
une heure — et une heure inventée sur le seul écran qui touche au direct est
pire que pas d'heure du tout.

La date vit dans sa PROPRE clé d'état, jamais dans le modèle : `fusionner()`
ignore ce qu'il ne connaît pas, et un champ que le panneau renverrait au PUT
ferait dater la publication de la dernière édition du navigateur.
"""
import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.core.overlay_layout import layout_par_defaut
from bot.core.overlay_layout_store import (
    LAYOUT_KEY, MAJ_KEY, charger_layout, date_maj, enregistrer_layout,
)
from bot.dashboard.routes.overlay import admin_router, public_router


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


class _StateMuette(_State):
    """Une base qui refuse d'écrire — coupure, disque plein, verrou."""

    async def set_state(self, key, value):
        raise RuntimeError("base indisponible")


def _client(db):
    app = FastAPI()
    app.include_router(public_router, prefix="/api/public")
    app.include_router(admin_router, prefix="/api/admin")
    app.state.wally = MagicMock()
    app.state.wally.db = db
    return TestClient(app)


async def test_enregistrer_pose_la_date():
    db = _State()
    await enregistrer_layout(db, layout_par_defaut())
    assert MAJ_KEY in db.rows
    assert await date_maj(db) == db.rows[MAJ_KEY]


async def test_la_date_est_locale_et_pas_utc():
    """L'hôte est en UTC, l'application raisonne en Europe/Paris. Un horodatage
    naïf afficherait « publié à 19:14 » pour une publication de 21:14."""
    db = _State()
    await enregistrer_layout(db, layout_par_defaut())
    # Un décalage explicite, quel qu'il soit : c'est son ABSENCE qui trompe.
    date = db.rows[MAJ_KEY]
    assert date[10] == "T"
    assert "+" in date[10:] or date.endswith("Z"), date


async def test_une_ecriture_ratee_ne_pose_pas_de_date():
    """Une date posée sur une écriture qui a échoué ferait dire au panneau
    « à l'antenne depuis 21:14 » alors que l'antenne diffuse toujours l'ancienne."""
    db = _StateMuette()
    await enregistrer_layout(db, layout_par_defaut())
    assert MAJ_KEY not in db.rows


async def test_pas_de_date_rangee_vaut_none_et_ne_leve_pas():
    assert await date_maj(None) is None
    assert await date_maj(_State()) is None


async def test_une_lecture_impossible_vaut_none():
    class _Cassee(_State):
        async def get_state(self, key):
            raise RuntimeError("base indisponible")

    assert await date_maj(_Cassee()) is None


def test_le_get_admin_joint_la_date_au_modele():
    db = _State({LAYOUT_KEY: json.dumps(layout_par_defaut()),
                 MAJ_KEY: "2026-08-21T21:14:00+02:00"})
    r = _client(db).get("/api/admin/overlay/layout")
    assert r.status_code == 200
    assert r.json()["maj"] == "2026-08-21T21:14:00+02:00"


def test_les_defauts_n_ont_pas_de_date():
    """`?defauts=1` sert la livraison, qui n'a jamais été publiée. Lui donner la
    date de la dernière publication ferait passer les valeurs d'origine pour ce
    qui est à l'antenne."""
    db = _State({MAJ_KEY: "2026-08-21T21:14:00+02:00"})
    r = _client(db).get("/api/admin/overlay/layout", params={"defauts": 1})
    assert r.status_code == 200
    assert r.json()["maj"] is None


def test_le_put_rend_la_date_qu_il_vient_de_poser():
    db = _State()
    client = _client(db)
    r = client.put("/api/admin/overlay/layout", json=layout_par_defaut())
    assert r.status_code == 200
    assert r.json()["maj"] == db.rows[MAJ_KEY]


def test_la_date_ne_part_pas_dans_le_modele_range():
    """Renvoyée par le GET, elle revient au PUT si le panneau ne la retire pas.
    Le modèle rangé ne doit jamais la porter — sinon `fusionner()` l'ignore et
    elle disparaît en silence, ou pire, elle survit et dérive."""
    db = _State()
    client = _client(db)
    envoi = {**layout_par_defaut(), "maj": "1999-01-01T00:00:00+01:00"}
    client.put("/api/admin/overlay/layout", json=envoi)
    assert "maj" not in json.loads(db.rows[LAYOUT_KEY])


async def test_charger_ignore_la_date():
    """`charger_layout` rend le modèle seul : la date est un aparté."""
    db = _State({MAJ_KEY: "2026-08-21T21:14:00+02:00"})
    layout = await charger_layout(db)
    assert "maj" not in layout
