# tests/test_compteur_messages.py
"""Le total de messages traités doit survivre aux redémarrages.

`state.message_count` repart de zéro à chaque boot — c'est voulu, le dashboard
veut savoir ce qui s'est passé depuis. La vitrine publique, elle, annonçait
« 1 » un quart d'heure après un rebuild. Le total de tous les temps est la
SOMME du report relu en base et du compteur de ce cycle.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from bot.db.database import Database
from bot.dashboard.app import (
    CLE_COMPTEUR_MESSAGES,
    charger_compteur_messages,
    create_dashboard_app,
    ranger_compteur_messages,
)
from bot.dashboard.state import AppState


async def _etat(tmp_path, **kwargs) -> AppState:
    db = await Database.create(str(tmp_path / "t.db"))
    emotion = MagicMock()
    emotion.get_state.return_value = {
        "anger": 0.0, "joy": 0.0, "sadness": 0.0, "curiosity": 0.0, "boredom": 0.0,
    }
    cfg = MagicMock()
    cfg.bot.dashboard_token = "testtoken"
    defauts = dict(
        config=cfg, db=db, emotion=emotion,
        memory=MagicMock(), persona=MagicMock(),
        primary_llm=MagicMock(), secondary_llm=MagicMock(),
        image_client=MagicMock(), token_manager=MagicMock(),
        twitch_api=None, discord_bot=None, twitch_bot=None,
        start_time=time.time() - 100,
    )
    defauts.update(kwargs)
    return AppState(**defauts)


# ── Lecture ────────────────────────────────────────────────────────────────

async def test_report_absent_vaut_zero(tmp_path):
    """Première mise en service : pas de clé, on repart de zéro sans râler."""
    state = await _etat(tmp_path)
    state.messages_avant_boot = 999          # valeur parasite à écraser
    await charger_compteur_messages(state)
    assert state.messages_avant_boot == 0
    await state.db.close()


async def test_report_relu_depuis_la_base(tmp_path):
    state = await _etat(tmp_path)
    await state.db.set_state(CLE_COMPTEUR_MESSAGES, "20781")
    await charger_compteur_messages(state)
    assert state.messages_avant_boot == 20781
    await state.db.close()


async def test_report_illisible_ne_fait_pas_planter(tmp_path):
    """Une valeur corrompue rend un compteur faux mais VISIBLE, pas un crash.

    Le compteur est une vitrine : il ne doit jamais empêcher le bot de démarrer.
    """
    state = await _etat(tmp_path)
    await state.db.set_state(CLE_COMPTEUR_MESSAGES, "pas un nombre")
    await charger_compteur_messages(state)
    assert state.messages_avant_boot == 0
    await state.db.close()


async def test_report_negatif_ramene_a_zero(tmp_path):
    state = await _etat(tmp_path)
    await state.db.set_state(CLE_COMPTEUR_MESSAGES, "-5")
    await charger_compteur_messages(state)
    assert state.messages_avant_boot == 0
    await state.db.close()


# ── Écriture ───────────────────────────────────────────────────────────────

async def test_range_la_somme_et_pas_le_cycle_seul(tmp_path):
    """C'est LE piège : ranger `message_count` seul écraserait le report.

    Le total redeviendrait « depuis le boot » à chaque redémarrage, ce qui est
    exactement le défaut qu'on corrige.
    """
    state = await _etat(tmp_path)
    state.messages_avant_boot = 20781
    state.message_count = 42
    await ranger_compteur_messages(state)
    assert await state.db.get_state(CLE_COMPTEUR_MESSAGES) == "20823"
    await state.db.close()


async def test_deux_rangements_de_suite_sont_idempotents(tmp_path):
    """La tâche périodique repasse toutes les 5 min : elle ne doit pas cumuler."""
    state = await _etat(tmp_path)
    state.messages_avant_boot = 100
    state.message_count = 7
    await ranger_compteur_messages(state)
    await ranger_compteur_messages(state)
    assert await state.db.get_state(CLE_COMPTEUR_MESSAGES) == "107"
    await state.db.close()


async def test_cycle_complet_arret_puis_redemarrage(tmp_path):
    """La séquence réelle, rejouée : c'est elle qui compte, pas les étapes.

    Un test par étape passait déjà avant le correctif — c'est l'enchaînement
    arrêt → redémarrage → nouveaux messages qui montre le double comptage ou la
    perte.
    """
    state = await _etat(tmp_path)
    await state.db.set_state(CLE_COMPTEUR_MESSAGES, "1000")

    # Cycle 1 : on relit, on traite 30 messages, on s'arrête proprement.
    await charger_compteur_messages(state)
    state.message_count = 30
    await ranger_compteur_messages(state)

    # Cycle 2 : nouveau processus, `message_count` repart de zéro.
    state.message_count = 0
    await charger_compteur_messages(state)
    assert state.messages_avant_boot == 1030
    state.message_count = 5
    await ranger_compteur_messages(state)

    assert await state.db.get_state(CLE_COMPTEUR_MESSAGES) == "1035"
    await state.db.close()


async def test_ecriture_en_echec_ne_leve_pas(tmp_path):
    """Base verrouillée ou disque plein : on perd le comptage, pas le bot."""
    state = await _etat(tmp_path)
    vraie_base = state.db
    state.db = MagicMock()
    state.db.set_state = AsyncMock(side_effect=OSError("disque plein"))
    await ranger_compteur_messages(state)      # ne doit pas lever
    await vraie_base.close()


# ── Ce que l'API publie ────────────────────────────────────────────────────

async def test_api_publique_rend_la_somme(tmp_path, monkeypatch):
    """`total_messages` est le total de tous les temps, pas celui du cycle."""
    monkeypatch.setattr("bot.dashboard.app.PUBLIC_UI_DIR", tmp_path / "absent")
    state = await _etat(tmp_path)
    state.messages_avant_boot = 20781
    state.message_count = 42
    app = create_dashboard_app(state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        d = (await c.get("/api/public/status")).json()
    assert d["total_messages"] == 20823
    # Le compteur du cycle reste publié à part : le dashboard s'en sert pour
    # dire ce qui s'est passé DEPUIS le redémarrage.
    assert d["messages_depuis_boot"] == 42
    await state.db.close()


@pytest.mark.parametrize("avant,cycle", [(0, 0), (0, 3), (20781, 0)])
async def test_total_jamais_inferieur_au_cycle(tmp_path, avant, cycle):
    state = await _etat(tmp_path, messages_avant_boot=avant, message_count=cycle)
    assert state.messages_avant_boot + state.message_count >= state.message_count
    await state.db.close()
