"""Routes « cerveau » du panel : validation, écriture EN MÉMOIRE, et vérité
sur ce qui s'applique à chaud ou au redémarrage."""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from bot.config import (
    AftermathConfig, BotConfig, CircadianConfig, FatigueConfig, FirecrawlConfig,
    HabituationConfig, ImageGenerationConfig, LLMConfig, LLMRoleConfig, MoodConfig,
    OpenAIConfig, SecondaryEmotionDef, TavilyConfig, WorldEvent,
)
from bot.dashboard.routes import config_cerveau as r


def _config():
    return types.SimpleNamespace(
        bot=BotConfig(trigger_names=["wally"], language_default="fr",
                      context_window_size=20, context_token_threshold=3000,
                      journal_time="21:00"),
        openai=OpenAIConfig(primary_model="gpt-5", secondary_model="deepseek-v4-flash",
                            temperature=0.8, max_tokens=1000, vision_model="gpt-5-nano"),
        llm=LLMConfig(primary=LLMRoleConfig(provider="openai", model="gpt-5.6-luna"),
                      secondary=LLMRoleConfig(provider="deepseek", model="deepseek-v4-flash")),
        mood=MoodConfig(), fatigue=FatigueConfig(), habituation=HabituationConfig(),
        circadian=CircadianConfig(), aftermath=AftermathConfig(),
        world_events={"stream_ended": WorldEvent(effects={"sadness": 0.35})},
        secondaries={
            "pride": SecondaryEmotionDef(a="joy", b="curiosity", threshold=0.4),
            "contempt": SecondaryEmotionDef(a="anger", b="boredom", threshold=[0.4, 0.5]),
        },
        cognitive_loop={"enabled": True, "provider": "deepseek", "model_pro": "deepseek-v4-flash"},
        response_gate={"enabled": True, "model": "deepseek-v4-flash"},
        tavily=TavilyConfig(), firecrawl=FirecrawlConfig(),
        image_generation=ImageGenerationConfig(),
        save=MagicMock(),
    )


def _requete(discord_bot=None):
    wally = types.SimpleNamespace(
        config=_config(), discord_bot=discord_bot, db=MagicMock(),
        primary_llm=types.SimpleNamespace(temperature=0.8),
        secondary_llm=types.SimpleNamespace(temperature=0.8),
    )
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally)))


def _cfg(req):
    return req.app.state.wally.config


async def _refuse(coro):
    with pytest.raises(HTTPException) as e:
        await coro
    assert e.value.status_code == 422
    assert isinstance(e.value.detail, str) and e.value.detail
    return e.value.detail


# ── Prise de parole ──────────────────────────────────────────────────────────

async def test_parole_rangee_et_pensees_annoncees_au_redemarrage():
    req = _requete()
    rep = await r.ecrire_parole(req, {"spontaneous_probability": 0.1,
                                      "spontaneous_channel_speak_enabled": True})
    assert _cfg(req).bot.spontaneous_probability == 0.1
    assert _cfg(req).bot.spontaneous_channel_speak_enabled is True
    assert rep["au_redemarrage"] == ["Pensées publiées d'elles-mêmes"]
    _cfg(req).save.assert_called_once()


async def test_parole_a_chaud_sans_annonce():
    rep = await r.ecrire_parole(_requete(), {"spontaneous_discord_enabled": False})
    assert rep["au_redemarrage"] == []


@pytest.mark.parametrize("corps", [
    {"spontaneous_probability": 1.5},
    {"spontaneous_probability": True},
    {"spontaneous_discord_enabled": "oui"},
    {"inconnu": 1},
    {"unanswered_question_delay_seconds": 400},  # oubli par défaut 300 ≤ délai
])
async def test_parole_refusee_sans_rien_ranger(corps):
    req = _requete()
    avant = _cfg(req).bot.spontaneous_probability
    await _refuse(r.ecrire_parole(req, corps))
    assert _cfg(req).bot.spontaneous_probability == avant
    _cfg(req).save.assert_not_called()


# ── Émotions ────────────────────────────────────────────────────────────────

async def test_emotions_partielles_et_atomiques():
    req = _requete()
    await _refuse(r.ecrire_emotions(req, {"emotion_inertia_factor": 0.2,
                                          "mood": {"alpha": 5}}))
    assert _cfg(req).bot.emotion_inertia_factor == 0.5, "rien ne doit être rangé"
    await r.ecrire_emotions(req, {"emotion_inertia_factor": 0.2,
                                  "habituation": {"exempt": ["anger", "joy", "anger"]}})
    assert _cfg(req).bot.emotion_inertia_factor == 0.2
    assert _cfg(req).habituation.exempt == ["anger", "joy"]


async def test_lassitude_refuse_une_emotion_inconnue():
    await _refuse(r.ecrire_emotions(_requete(), {"habituation": {"exempt": ["rage"]}}))


async def test_circadien_garde_la_forme_et_refuse_les_chevauchements():
    req = _requete()
    await r.ecrire_circadien(req, {"enabled": False,
                                   "periods": {"night": {"hours": [0, 6], "anger": 1.5}}})
    circ = _cfg(req).circadian
    assert circ.enabled is False
    assert circ.periods["night"].anger == 1.5
    assert set(circ.periods) == {"night", "morning", "afternoon", "evening"}
    await _refuse(r.ecrire_circadien(req, {"periods": {"night": {"hours": [0, 8]}}}))
    await _refuse(r.ecrire_circadien(req, {"periods": {"brunch": {"hours": [10, 11]}}}))
    await _refuse(r.ecrire_circadien(req, {"periods": {"night": {"hours": [6, 2]}}}))
    assert circ.periods["night"].hours == [0, 6]


async def test_contrecoup_refuse_l_ennui_en_source_et_la_boucle():
    req = _requete()
    await _refuse(r.ecrire_contrecoup(req, {"rules": {"amertume": {"source": "boredom"}}}))
    await _refuse(r.ecrire_contrecoup(req, {"rules": {"amertume": {"target": "anger"}}}))
    await r.ecrire_contrecoup(req, {"rules": {"amertume": {"ratio": 0.5}}})
    assert _cfg(req).aftermath.rules["amertume"].ratio == 0.5


async def test_evenements_remplacent_les_effets_sans_les_zeros():
    req = _requete()
    await r.ecrire_evenements(req, {"stream_ended": {"effects": {
        "sadness": 0.2, "joy": 0, "anger": 0.1}}})
    assert _cfg(req).world_events["stream_ended"].effects == {"sadness": 0.2, "anger": 0.1}
    await _refuse(r.ecrire_evenements(req, {"raid": {"effects": {}}}))


async def test_secondaires_gardent_un_seuil_double():
    req = _requete()
    await r.ecrire_secondaires(req, {"contempt": {"threshold": [0.5, 0.6]},
                                     "pride": {"threshold": 0.45}})
    assert _cfg(req).secondaries["contempt"].threshold == [0.5, 0.6]
    await _refuse(r.ecrire_secondaires(req, {"contempt": {"threshold": 0.5}}))
    await _refuse(r.ecrire_secondaires(req, {"pride": {"threshold": 0.3}}))


# ── Mémoire ─────────────────────────────────────────────────────────────────

async def test_memoire():
    req = _requete()
    assert (await r.lire_memoire(req))["prelude_window_size"] == 15
    await r.ecrire_memoire(req, {"prelude_window_size": 30, "link_min_confidence": 0.8})
    assert _cfg(req).bot.prelude_window_size == 30
    await _refuse(r.ecrire_memoire(req, {"memory_context_max_tokens": 10}))


# ── Modèles ─────────────────────────────────────────────────────────────────

def _bot_avec_cognition():
    raisonnement = types.SimpleNamespace(_llm=types.SimpleNamespace(model="deepseek-v4-flash"))
    persona = types.SimpleNamespace(_llm=types.SimpleNamespace(model="deepseek-v4-flash"))
    boucle = types.SimpleNamespace(_reasoning=raisonnement,
                                   _dispatcher=types.SimpleNamespace(_persona=persona),
                                   _web_search_cooldown_s=2700)
    gate = types.SimpleNamespace(_llm=types.SimpleNamespace(model="deepseek-v4-flash"))
    vision = types.SimpleNamespace(_client=types.SimpleNamespace(model="gpt-5-nano"))
    return types.SimpleNamespace(cognitive_loop=boucle, response_gate=gate, vision=vision)


async def test_modeles_pousses_dans_les_clients_vivants():
    bot = _bot_avec_cognition()
    req = _requete(bot)
    rep = await r.ecrire_modeles(req, {
        "cognition": {"provider": "deepseek", "model_pro": "deepseek-v4-pro"},
        "gate": {"model": "deepseek-v4-pro"},
        "vision": {"model": "gpt-5-mini"},
        "tavily": {"cognitive_cooldown_minutes": 10},
    })
    assert rep["au_redemarrage"] == []
    assert bot.cognitive_loop._reasoning._llm.model == "deepseek-v4-pro"
    assert bot.cognitive_loop._dispatcher._persona._llm.model == "deepseek-v4-pro"
    assert bot.response_gate._llm.model == "deepseek-v4-pro"
    assert bot.vision._client.model == "gpt-5-mini"
    assert bot.cognitive_loop._web_search_cooldown_s == 600
    assert _cfg(req).cognitive_loop["model_pro"] == "deepseek-v4-pro"
    assert _cfg(req).openai.vision_model == "gpt-5-mini"


async def test_changer_de_fournisseur_construit_un_client_neuf():
    bot = _bot_avec_cognition()
    await r.ecrire_modeles(_requete(bot), {"cognition": {"provider": "openai", "model_pro": "gpt-5-mini"}})
    client = bot.cognitive_loop._reasoning._llm
    assert type(client).__name__ == "OpenAILLMClient"
    assert client.model == "gpt-5-mini"


async def test_sans_cognition_vivante_le_panel_annonce_le_redemarrage():
    rep = await r.ecrire_modeles(_requete(None), {
        "cognition": {"model_pro": "deepseek-v4-pro"},
        "gate": {"model": "deepseek-v4-pro"},
    })
    assert rep["au_redemarrage"] == ["modèle de la cognition", "modèle du filtre de réponse"]


async def test_reenregistrer_sans_changement_n_annonce_rien():
    rep = await r.ecrire_modeles(_requete(None), {
        "cognition": {"provider": "deepseek", "model_pro": "deepseek-v4-flash"},
        "vision": {"model": "gpt-5-nano"},
    })
    assert rep["au_redemarrage"] == []


async def test_modeles_atomiques_et_refus():
    req = _requete()
    await _refuse(r.ecrire_modeles(req, {"tavily": {"monthly_limit": 5},
                                         "cognition": {"provider": "claude"}}))
    assert _cfg(req).tavily.monthly_limit == 200
    await _refuse(r.ecrire_modeles(req, {"vision": {"model": "gpt 5; rm"}}))
    await _refuse(r.ecrire_modeles(req, {"temperatures": {"primary": 3}}))


async def test_temperatures_miroir_et_clients():
    req = _requete()
    await r.ecrire_modeles(req, {"temperatures": {"primary": 0.3, "secondary": 1.1}})
    w = req.app.state.wally
    assert w.config.llm.primary.temperature == 0.3 == w.config.openai.temperature
    assert w.primary_llm.temperature == 0.3 and w.secondary_llm.temperature == 1.1


async def test_temperature_dite_ignoree_quand_elle_l_est():
    d = await r.lire_modeles(_requete())
    assert d["temperatures"]["primary"]["lue"] is False   # gpt-5.6 : Responses API
    assert d["temperatures"]["secondary"]["lue"] is True  # DeepSeek sans réflexion


# ── Images spontanées ───────────────────────────────────────────────────────

async def test_images_ids_en_chaines_et_annonce_si_ouverture_change():
    req = _requete()
    rep = await r.ecrire_images(req, {"autonomous_channel_ids": ["938504877464768603", "938504877464768603"],
                                      "autonomous_daily_limit": 0})
    ig = _cfg(req).image_generation
    assert ig.autonomous_channel_ids == ["938504877464768603"]
    assert ig.autonomous_daily_limit == 0
    assert rep["au_redemarrage"]
    rep = await r.ecrire_images(req, {"autonomous_channel_ids": ["938504877464768603"],
                                      "autonomous_cooldown_minutes": 30})
    assert rep["au_redemarrage"] == []
    await _refuse(r.ecrire_images(req, {"autonomous_channel_ids": ["#general"]}))
    await _refuse(r.ecrire_images(req, {"autonomous_daily_limit": -2}))


# ── Câblage HTTP ────────────────────────────────────────────────────────────

async def test_routes_montees_sous_api_admin(async_client):
    h = {"Authorization": "Bearer testtoken"}
    r1 = await async_client.get("/api/admin/cerveau/memoire", headers=h)
    assert r1.status_code == 200 and r1.json()["prelude_window_size"] == 15
    r2 = await async_client.put("/api/admin/cerveau/memoire", headers=h,
                                json={"prelude_window_size": 0})
    assert r2.status_code == 422
    assert "Messages de prélude" in r2.json()["detail"]
