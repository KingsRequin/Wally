"""Le rangement du layout dans `bot_state`.

Patron du `_State` simulé repris de `tests/test_overlay_etat_partie_persist.py`.
"""
import json

import pytest

from bot.core.overlay_layout import ELEMENTS, layout_par_defaut
from bot.core.overlay_layout_store import (
    LAYOUT_KEY, charger_layout, enregistrer_layout,
)


class _State:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


@pytest.mark.asyncio
async def test_charger_sans_rien_en_base_rend_les_defauts():
    assert await charger_layout(_State()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_un_json_illisible_rend_les_defauts():
    """Une écriture interrompue laisse du JSON tronqué. L'overlay doit quand
    même s'afficher."""
    db = _State({LAYOUT_KEY: '{"scenes": [{"slug": "jeu"'})
    assert await charger_layout(db) == layout_par_defaut()


@pytest.mark.asyncio
async def test_charger_sans_base_rend_les_defauts():
    """`db=None` arrive avant la connexion du bot : la page ne doit pas
    attendre pour s'afficher."""
    assert await charger_layout(None) == layout_par_defaut()


@pytest.mark.asyncio
async def test_enregistrer_puis_recharger_conserve_les_positions():
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 12.5
    await enregistrer_layout(db, layout)
    relu = await charger_layout(db)
    assert relu["scenes"][0]["elements"]["avatar"]["x"] == 12.5


@pytest.mark.asyncio
async def test_enregistrer_valide_avant_de_ranger():
    """Ce qui entre est fusionné : une valeur hors bornes n'atteint pas la
    base, sinon elle y resterait jusqu'au prochain enregistrement."""
    db = _State()
    layout = layout_par_defaut()
    layout["scenes"][0]["elements"]["avatar"]["x"] = 5000.0
    rendu = await enregistrer_layout(db, layout)
    assert rendu["scenes"][0]["elements"]["avatar"]["x"] == 100.0
    assert json.loads(db.rows[LAYOUT_KEY])["scenes"][0]["elements"]["avatar"]["x"] == 100.0


@pytest.mark.asyncio
async def test_enregistrer_sans_base_ne_leve_pas():
    """Le panneau doit répondre même si la base est absente — il rend alors ce
    qu'il a compris, sans prétendre l'avoir rangé."""
    assert await enregistrer_layout(None, layout_par_defaut()) == layout_par_defaut()


@pytest.mark.asyncio
async def test_toutes_les_cles_delements_survivent_a_un_aller_retour():
    db = _State()
    await enregistrer_layout(db, layout_par_defaut())
    relu = await charger_layout(db)
    for scene in relu["scenes"]:
        assert set(scene["elements"]) == set(ELEMENTS)
