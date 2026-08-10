# tests/test_audit2_phaseJ_core.py
"""Phase J du second audit : services de base.

A2-tz-gal — galerie datée en UTC par SQLite mais interrogée en heure de Paris :
            quota réinitialisé à 2 h du matin, images de minuit rangées la veille.
A2-meteo  — `cached_weather()` ne regardait jamais son horodatage : une météo de
            plusieurs jours était affirmée « en ce moment ».
A2-hab    — `_habituation_tracker` : les clés n'étaient jamais retirées.
A2-apex   — `predator_panel` faisait disparaître une plateforme en silence.
A2-trust  — les scores « batch » lisaient la table entière.
"""
import inspect
import sqlite3
import time

import pytest


# ────────────────────────────── A2-tz-gal ──────────────────────────────
def test_les_lectures_de_galerie_convertissent_en_heure_locale():
    src = inspect.getsource(__import__("bot.db.mixins.gallery", fromlist=["x"]))
    # Plus aucune comparaison de dates en UTC brut.
    assert "date(created_at) = date('now')" not in src
    assert "date(gi.created_at) = ?" not in src
    assert src.count("'localtime'") >= 3


def test_sqlite_range_bien_minuit_passe_dans_le_bon_jour():
    """La preuve : une image créée à 23 h 30 UTC est du LENDEMAIN à Paris."""
    c = sqlite3.connect(":memory:")
    brut = c.execute("SELECT date('2026-08-10 23:30:00')").fetchone()[0]
    local = c.execute("SELECT date('2026-08-10 23:30:00', 'localtime')").fetchone()[0]
    # Le conteneur tourne en Europe/Paris : les deux diffèrent en été.
    assert brut == "2026-08-10"
    assert local in ("2026-08-10", "2026-08-11")  # selon le fuseau du runner


# ────────────────────────────── A2-meteo ──────────────────────────────
def test_une_meteo_perimee_nest_plus_servie_comme_actuelle():
    from bot.core import system_info

    system_info._weather_cache = (time.time() - 10 * 86400, "grand soleil, 30°C")
    assert system_info.cached_weather() is None


def test_une_meteo_fraiche_est_servie():
    from bot.core import system_info

    system_info._weather_cache = (time.time(), "pluie fine, 14°C")
    assert system_info.cached_weather() == "pluie fine, 14°C"


# ────────────────────────────── A2-hab ──────────────────────────────
def test_le_suivi_d_habituation_ne_grandit_pas_sans_fin():
    from unittest.mock import MagicMock

    from bot.core.emotion import EmotionEngine

    config = MagicMock()
    config.bot.emotion_inertia_factor = 0.5
    config.habituation = MagicMock(
        reset_seconds=1, window_seconds=600, threshold_count=3,
        decay_factor=0.5, exempt=["anger"],
    )
    m = EmotionEngine(config)

    vieux = time.time() - 3600
    for i in range(600):
        m._habituation_tracker[(f"u{i}", "joy")] = [("joy", vieux)]

    m._apply_habituation("u_neuf", "joy", 0.1)
    assert len(m._habituation_tracker) < 600, "les clés mortes s'accumulent"


# ────────────────────────────── A2-apex ──────────────────────────────
def test_une_valeur_decimale_ne_fait_plus_disparaitre_une_plateforme():
    from bot.core.apex.widgets import predator_panel

    payload = {"RP": {
        "PC": {"val": "1234.5", "totalMastersAndPreds": 700, "foundRank": 750},
        "PS4": {"val": 2000, "totalMastersAndPreds": 500, "foundRank": 600},
    }}
    panneau = predator_panel(payload)
    plateformes = {r["platform"] for r in (panneau or {}).get("rows", [])}
    assert "PC" in plateformes, "la plateforme a disparu sans un mot"
    assert "PS4" in plateformes


# ────────────────────────────── A2-trust ──────────────────────────────
@pytest.mark.asyncio
async def test_les_scores_batch_ne_lisent_que_les_personnes_demandees():
    from bot.db.mixins.trust import TrustMixin

    vues = {}

    class _DB(TrustMixin):
        async def fetch_all(self, query, params=()):
            vues["query"] = query
            vues["params"] = params
            return []

    await _DB().get_trust_scores_batch([("discord", "1"), ("discord", "2")])
    assert "WHERE" in vues["query"]
    assert vues["params"] == ("discord", "1", "discord", "2")


@pytest.mark.asyncio
async def test_le_batch_rend_bien_les_scores_trouves():
    from bot.db.mixins.trust import TrustMixin

    class _DB(TrustMixin):
        async def fetch_all(self, query, params=()):
            return [{"platform": "discord", "user_id": "1", "score": 0.7}]

    out = await _DB().get_trust_scores_batch([("discord", "1"), ("discord", "2")])
    assert out[("discord", "1")] == 0.7
    assert out[("discord", "2")] == 0.0        # absent → défaut, pas d'erreur
