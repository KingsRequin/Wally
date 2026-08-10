# tests/test_audit2_urgences.py
"""Les trois urgences du second audit (2026-08-10).

A2-1 — les souvenirs privés d'un tiers fuitaient parce qu'il avait PARLÉ :
       l'étiquette d'auteur alimentait la détection de mentions.
A2-7 — RÉGRESSION introduite en phase 8 : le vieillissement d'arrêt tournait
       AVANT le chargement de mood/fatigue/affinités, qui l'écrasaient.
A2-8 — le callback OAuth Twitch n'était lié à rien : en mode preview le jeton
       est la constante publique `__preview__`.
"""
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException


# ────────────────────────────── A2-1 ──────────────────────────────
@pytest.mark.asyncio
async def test_avoir_parle_ne_declenche_pas_l_injection_de_ses_souvenirs():
    from bot.discord import handlers

    bot = MagicMock()
    bot.memory._alias_cache = {"nickname:alice": "discord:111"}
    bot.memory.search = AsyncMock(return_value="Alice déteste son patron")
    bot.db.list_memory_users = AsyncMock(return_value=[])

    # Alice a parlé, mais personne ne la NOMME.
    prelude = [{"author": "Alice (@alice)", "content": "salut tout le monde"}]
    out = await handlers._third_party_mention_context(
        bot, "discord", "discord:222", prelude, []
    )
    assert "Alice" not in out


@pytest.mark.asyncio
async def test_une_vraie_mention_declenche_toujours_l_injection():
    from bot.discord import handlers

    bot = MagicMock()
    bot.memory._alias_cache = {"nickname:alice": "discord:111"}
    bot.memory.search = AsyncMock(return_value="Alice déteste son patron")
    bot.db.list_memory_users = AsyncMock(return_value=[])

    prelude = [{"author": "Bob (@bob)", "content": "tu as vu Alice hier ?"}]
    out = await handlers._third_party_mention_context(
        bot, "discord", "discord:222", prelude, []
    )
    assert "Alice" in out


# ────────────────────────────── A2-7 ──────────────────────────────
def _config(lam=0.5):
    config = MagicMock()
    cfg = MagicMock(decay_lambda=lam, boredom_rise_per_hour=0.1)
    config.emotions = {e: cfg for e in ("anger", "joy", "sadness", "curiosity", "boredom")}
    config.bot.emotion_inertia_factor = 0.5
    config.bot.emotion_peak_threshold = 0.7
    config.emotional_memory.decay_lambda_per_day = 0.5
    return config


@pytest.mark.asyncio
async def test_l_affinite_par_personne_vieillit_aussi_a_travers_un_redemarrage():
    """Le cliquet que le rattrapage devait supprimer, et qu'il laissait intact."""
    from bot.core.emotion import EmotionEngine

    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.8})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.load_emotion_state_age = AsyncMock(return_value=time.time() - 12 * 3600)
    db.fetch_all = AsyncMock(return_value=[
        {"user_id": "1", "platform": "discord", "emotion": "joy",
         "affinity": 0.9, "interaction_count": 5},
    ])

    m = EmotionEngine(_config(), db=db)
    await m.load_state()

    affinite = m._user_affinity[("1", "discord")]["joy"]
    assert affinite < 0.9, "l'affinité chargée écrase le vieillissement"


@pytest.mark.asyncio
async def test_l_ennui_monte_pendant_un_arret():
    from bot.core.emotion import EmotionEngine

    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"boredom": 0.0})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.load_emotion_state_age = AsyncMock(return_value=time.time() - 12 * 3600)
    db.fetch_all = AsyncMock(return_value=[])

    m = EmotionEngine(_config(), db=db)
    await m.load_state()

    assert m.get_state()["boredom"] > 0.5, "12 h d'absence sans le moindre ennui"


@pytest.mark.asyncio
async def test_les_emotions_de_base_vieillissent_toujours():
    """Non-régression du correctif de phase 8 lui-même."""
    import math

    from bot.core.emotion import EmotionEngine

    db = MagicMock()
    db.load_emotion_state = AsyncMock(return_value={"anger": 0.8})
    db.load_mood_state = AsyncMock(return_value={})
    db.load_fatigue_state = AsyncMock(return_value={})
    db.load_emotion_state_age = AsyncMock(return_value=time.time() - 12 * 3600)
    db.fetch_all = AsyncMock(return_value=[])

    m = EmotionEngine(_config(lam=0.5), db=db)
    await m.load_state()
    assert m.get_state()["anger"] == pytest.approx(0.8 * math.exp(-0.5 * 12), abs=0.02)


# ────────────────────────────── A2-8 ──────────────────────────────
def _requete(session):
    r = MagicMock()
    r.app.state.wally.db.get_setup_session = AsyncMock(return_value=session)
    r.app.state.wally.db.save_setup_session = AsyncMock()
    r.app.state.wally.db.get_setup_invite = AsyncMock(
        return_value={"is_preview": 1, "expires_at": None, "used_at": None}
    )
    return r


@pytest.mark.asyncio
async def test_un_state_force_en_mode_preview_est_refuse():
    """`__preview__` est une constante publique : le jeton seul ne prouve rien."""
    from bot.dashboard.routes.setup import twitch_callback

    r = _requete({"twitch_oauth_nonce": "le-vrai-nonce"})
    r.query_params = {"code": "abc", "state": "__preview__:__preview__:bot"}

    with pytest.raises(HTTPException) as e:
        await twitch_callback(r, "__preview__")
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_un_callback_sans_nonce_en_session_est_refuse():
    from bot.dashboard.routes.setup import twitch_callback

    r = _requete({})                      # aucun `authorize` n'a été émis
    r.query_params = {"code": "abc", "state": "__preview__:nimporte:bot"}

    with pytest.raises(HTTPException) as e:
        await twitch_callback(r, "__preview__")
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_le_nonce_est_brule_apres_usage():
    """Un `code` rejoué ne doit pas repasser."""
    from bot.dashboard.routes.setup import twitch_callback

    r = _requete({"twitch_oauth_nonce": "n1", "twitch_client_id": "cid",
                  "twitch_client_secret": "sec", "twitch_redirect_uri": "http://x"})
    r.query_params = {"code": "abc", "state": "__preview__:n1:bot"}

    # L'échange réseau échouera (pas de vrai Twitch), peu importe : le nonce
    # doit avoir été invalidé AVANT.
    try:
        await twitch_callback(r, "__preview__")
    except Exception:
        pass

    appels = [c.args[1] for c in r.app.state.wally.db.save_setup_session.await_args_list]
    assert any(a.get("twitch_oauth_nonce") == "" for a in appels)


def test_l_url_d_autorisation_emet_un_nonce():
    import inspect

    from bot.dashboard.routes import setup

    src = inspect.getsource(setup)
    assert "nonce = uuid.uuid4().hex" in src
    assert '"state": f"{token}:{nonce}:{account_type}"' in src
