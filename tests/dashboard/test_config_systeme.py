"""Routes « système » du panel : transcription vocale, veille RSS, salons de service.

Ce qu'on protège : une écriture refusée ne laisse RIEN en mémoire, les ids
Discord restent des chaînes à l'aller et des `int` en config, et chaque
écriture atteint ses lecteurs vivants (service vocal, boucle cognitive,
souvenir du salon de live).
"""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bot.config import BotConfig, RSSFeedDef, RSSFeedsConfig, VoiceConfig, WebChatConfig
from bot.dashboard.routes import config_systeme as cs

SALON_A = "1485380606224502844"
SALON_B = "1267757914953875487"


def _requete(corps=None, discord_bot=None):
    config = types.SimpleNamespace(
        bot=BotConfig(trigger_names=["wally"], language_default="fr", context_window_size=20,
                      context_token_threshold=3000, journal_time="21:00",
                      journal_channel_id=None, bedroom_channel_id=int(SALON_A),
                      stream_voice_channel_id=int(SALON_B)),
        voice=VoiceConfig(requesters=[{"discord_id": "610550333042589752", "twitch_id": 12345,
                                       "twitch_login": "azrael", "apex_name": "Az",
                                       "apex_uid": "1000"}]),
        rss=RSSFeedsConfig(),
        web_chat=WebChatConfig(),
        save=MagicMock(),
    )
    db = MagicMock()
    db.delete_state = AsyncMock()
    wally = types.SimpleNamespace(config=config, discord_bot=discord_bot, db=db)

    async def _json():
        return corps

    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(wally=wally)),
                                 json=_json)


def _config(req):
    return req.app.state.wally.config


# ─── Voix ────────────────────────────────────────────────────────────────────

async def test_lire_voix_rend_les_ids_en_chaines():
    d = await cs.lire_voix(_requete())
    assert d["requesters"][0]["discord_id"] == "610550333042589752"
    assert d["requesters"][0]["twitch_id"] == "12345"
    assert d["stt_provider"] == "azure"


async def test_ecrire_voix_range_et_recharge_le_service_du_bot_discord():
    service = MagicMock()
    req = _requete({"stt_provider": "remote_stream", "remote_stt_max_connections": 3,
                    "overflow_stt_provider": "xai", "vad_silence_timeout_s": 0.8},
                   discord_bot=types.SimpleNamespace(voice_service=service))
    await cs.ecrire_voix(req)
    v = _config(req).voice
    assert (v.stt_provider, v.remote_stt_max_connections, v.overflow_stt_provider) == ("remote_stream", 3, "xai")
    assert v.vad_silence_timeout_s == 0.8
    _config(req).save.assert_called_once()
    service.reload_config.assert_called_once_with(v)


async def test_ecrire_voix_sans_bot_discord_ne_leve_pas():
    req = _requete({"whisper_model": "base"})
    await cs.ecrire_voix(req)
    assert _config(req).voice.whisper_model == "base"


@pytest.mark.parametrize("corps", [
    {"stt_provider": "openai"},
    {"remote_stt_url": "http://192.168.1.49:9090"},
    {"remote_stt_max_connections": 0},
    {"overflow_stt_provider": "deepgram"},
    {"whisper_model": "gigantesque"},
    {"vad_silence_timeout_s": True},
    {"requesters": [{"twitch_login": "sans_identite"}]},
    {"requesters": [{"discord_id": "abc"}]},
    {"requesters": [{"discord_id": "610550333042589752"}, {"discord_id": "610550333042589752"}]},
    {"requesters": [{"discord_id": "610550333042589752", "apex_platform": "Switch"}]},
])
async def test_une_voix_refusee_ne_touche_a_rien(corps):
    req = _requete({"stt_provider": "faster_whisper", **corps})
    avant = VoiceConfig(**vars(_config(req).voice))
    with pytest.raises(HTTPException) as e:
        await cs.ecrire_voix(req)
    assert e.value.status_code == 422
    assert vars(_config(req).voice) == vars(avant)
    _config(req).save.assert_not_called()


async def test_les_demandeurs_gardent_la_forme_lue_par_apex():
    from bot.core.apex.seed import uid_declare

    req = _requete({"requesters": [
        {"discord_id": "610550333042589752", "twitch_id": "12345", "twitch_login": "Azrael",
         "apex_name": "AzraelTTV", "apex_uid": "2000", "apex_platform": ""},
        {"discord_id": "", "twitch_id": "999", "twitch_login": "", "apex_name": "", "apex_uid": ""},
    ]})
    await cs.ecrire_voix(req)
    rq = _config(req).voice.requesters
    assert rq[0] == {"discord_id": "610550333042589752", "twitch_id": "12345",
                     "twitch_login": "azrael", "apex_name": "AzraelTTV", "apex_uid": "2000"}
    assert rq[1] == {"twitch_id": "999"}
    assert uid_declare(rq, "azraelttv") == "2000"


# ─── Veille ──────────────────────────────────────────────────────────────────

async def test_ecrire_veille_remplace_les_flux():
    req = _requete({"feeds": [
        {"name": "Korben", "kind": "rss", "url": "https://korben.info/feedfull", "role": "stimulus",
         "lang": "FR", "enabled": True, "appid": "ignoré"},
        {"name": "Apex", "kind": "steam", "url": "https://x", "appid": "1172470", "role": "knowledge",
         "lang": "en", "enabled": False},
    ], "retention_days": 30})
    d = await cs.ecrire_veille(req)
    r = _config(req).rss
    assert r.feeds == [
        RSSFeedDef(name="Korben", url="https://korben.info/feedfull", role="stimulus", lang="fr",
                   enabled=True, kind="rss", appid=""),
        RSSFeedDef(name="Apex", url="", role="knowledge", lang="en", enabled=False,
                   kind="steam", appid="1172470"),
    ]
    assert r.retention_days == 30
    assert d["feeds"][1]["appid"] == "1172470"
    _config(req).save.assert_called_once()


@pytest.mark.parametrize("corps", [
    {"feeds": [{"name": "", "url": "https://a"}]},
    {"feeds": [{"name": "A", "url": "https://a"}, {"name": "a", "url": "https://b"}]},
    {"feeds": [{"name": "A", "url": "ftp://a"}]},
    {"feeds": [{"name": "A", "kind": "steam", "appid": ""}]},
    {"feeds": [{"name": "A", "url": "https://a", "role": "autre"}]},
    {"feeds": [{"name": "A", "url": "https://a", "lang": "français"}]},
    {"poll_interval_minutes": 1},
    {"enabled": "oui"},
])
async def test_une_veille_refusee_ne_touche_a_rien(corps):
    req = _requete({"retention_days": 20, **corps})
    flux_avant = list(_config(req).rss.feeds)
    with pytest.raises(HTTPException) as e:
        await cs.ecrire_veille(req)
    assert e.value.status_code == 422
    assert _config(req).rss.feeds == flux_avant
    assert _config(req).rss.retention_days == 10
    _config(req).save.assert_not_called()


# ─── Salons de service ───────────────────────────────────────────────────────

async def test_lire_salons_rend_des_chaines():
    d = await cs.lire_salons(_requete())
    assert d == {"web_chat_cooldown_seconds": 10, "journal_channel_id": "",
                 "bedroom_channel_id": SALON_A, "stream_voice_channel_id": SALON_B}


async def test_changer_la_chambre_previent_la_boucle_et_le_vocal_oublie_le_souvenir():
    boucle = MagicMock()
    req = _requete({"bedroom_channel_id": SALON_B, "stream_voice_channel_id": SALON_A,
                    "journal_channel_id": SALON_A, "web_chat_cooldown_seconds": 30},
                   discord_bot=types.SimpleNamespace(cognitive_loop=boucle))
    await cs.ecrire_salons(req)
    b = _config(req).bot
    assert (b.bedroom_channel_id, b.stream_voice_channel_id, b.journal_channel_id) == (
        int(SALON_B), int(SALON_A), int(SALON_A))
    assert _config(req).web_chat.cooldown_seconds == 30
    boucle.poser_chambre.assert_called_once_with(int(SALON_B))
    req.app.state.wally.db.delete_state.assert_awaited_once()


async def test_un_salon_inchange_ne_touche_ni_la_boucle_ni_le_souvenir():
    boucle = MagicMock()
    req = _requete({"bedroom_channel_id": SALON_A, "stream_voice_channel_id": SALON_B},
                   discord_bot=types.SimpleNamespace(cognitive_loop=boucle))
    await cs.ecrire_salons(req)
    boucle.poser_chambre.assert_not_called()
    req.app.state.wally.db.delete_state.assert_not_awaited()


async def test_vider_un_salon_le_met_a_none():
    req = _requete({"bedroom_channel_id": ""})
    await cs.ecrire_salons(req)
    assert _config(req).bot.bedroom_channel_id is None


@pytest.mark.parametrize("corps", [
    {"journal_channel_id": "pas-un-id"},
    {"journal_channel_id": 12},
    {"web_chat_cooldown_seconds": -1},
])
async def test_des_salons_refuses_ne_touchent_a_rien(corps):
    req = _requete({"bedroom_channel_id": SALON_B, **corps})
    with pytest.raises(HTTPException) as e:
        await cs.ecrire_salons(req)
    assert e.value.status_code == 422
    assert _config(req).bot.bedroom_channel_id == int(SALON_A)
    _config(req).save.assert_not_called()


# ─── Lecteurs vivants ────────────────────────────────────────────────────────

def test_poser_chambre_change_la_cible_de_la_boucle():
    from bot.intelligence.cognitive_loop import CognitiveLoop

    boucle = CognitiveLoop.__new__(CognitiveLoop)
    boucle.poser_chambre(int(SALON_A))
    assert boucle._bedroom_channel_id == SALON_A
    boucle.poser_chambre(None)
    assert boucle._bedroom_channel_id is None


async def test_le_formulaire_vocal_historique_recharge_bien_le_service():
    """`/api/admin/config` lisait `voice_service` sur l'AppState, où il n'existe
    pas : le rechargement « à chaud » annoncé n'avait jamais lieu."""
    from bot.dashboard.routes.admin import _appliquer_config

    service = MagicMock()
    req = _requete(discord_bot=types.SimpleNamespace(voice_service=service))
    cfg = _config(req)
    await _appliquer_config(req, {"voice": {"vad_aggressiveness": 1}}, req.app.state.wally, cfg)
    service.reload_config.assert_called_once_with(cfg.voice)


async def test_un_moteur_change_en_session_s_applique_au_join_suivant(monkeypatch):
    """`reload_config` différait le changement « au prochain join », mais `join()`
    ne reconstruisait rien : le moteur ne changeait qu'au redémarrage."""
    from bot.discord.voice import service as mod
    from bot.discord.voice.service import VoiceService

    vs = VoiceService.__new__(VoiceService)
    vs._bot = types.SimpleNamespace(config=types.SimpleNamespace(
        bot=types.SimpleNamespace(name="Wally", trigger_names=[])))
    vs._cfg = VoiceConfig(stt_provider="faster_whisper")
    vs._vc = object()
    vs._streaming = None
    vs._stt = object()
    vs._stt_phrases = ["Wally"]
    vs._maintain_task = None
    monkeypatch.setattr(mod, "build_tts", lambda cfg: object())
    construits = []
    monkeypatch.setattr(vs, "_build_stt_pipeline", lambda cfg, phrases: construits.append(cfg.stt_provider))

    vs.reload_config(VoiceConfig(stt_provider="azure"))
    assert construits == []                  # rien pendant la session

    vs._vc = None
    monkeypatch.setattr(mod, "poser_la_borne_rtp", lambda: None)
    salon = types.SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError("stop")))
    with pytest.raises(RuntimeError):
        await vs._join_locked(salon, None, False)
    assert construits == ["azure"]
