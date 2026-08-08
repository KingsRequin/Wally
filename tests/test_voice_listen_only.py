"""Mode écoute — le compagnon de stream entend sans jamais parler.

Wally est dans le vocal d'Azraël PENDANT le live. S'il prenait la parole à
l'oral, il couvrirait le streamer et serait réinjecté dans son micro. Sa
réaction passe par l'overlay, que les viewers voient et que le streamer ne voit
pas.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.discord.voice.service import VoiceService


def _service():
    with patch.object(VoiceService, "_build_stt_pipeline", lambda *a, **k: None), \
         patch("bot.discord.voice.service.build_tts", lambda cfg: MagicMock()), \
         patch("bot.discord.voice.service._ensure_opus", lambda: None), \
         patch("bot.discord.voice.service.make_voice_tool_executor", lambda *a, **k: None):
        bot = MagicMock()
        bot.config.bot.name = "Wally"
        bot.config.bot.trigger_names = ["wally"]
        cfg = SimpleNamespace(vad_aggressiveness=2, vad_silence_timeout_s=1.0,
                              auto_leave_minutes=5)
        return VoiceService(bot, cfg)


@pytest.mark.asyncio
async def test_en_mode_ecoute_il_ne_parle_pas():
    """Le garde est en profondeur : même un appel direct à speak() est refusé."""
    svc = _service()
    svc._vc = MagicMock()
    svc.listen_only = True
    svc._tts.synthesize = AsyncMock()
    await svc.speak("je devrais me taire")
    svc._tts.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_parole_entendue_devient_perception_pas_reponse():
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_overheard = AsyncMock(return_value=None)
    narrator.count_spoken_vote.return_value = False
    svc._bot.overlay_narrator = narrator
    feed = MagicMock()

    with patch("bot.core.stream_feed.active_stream_feed", return_value=feed), \
         patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()) as brain:
        user = SimpleNamespace(id=42, display_name="Azrael", name="azrael")
        await svc._dispatch_transcript(user, "j'ai encore raté mon saut", 120.0)
        await asyncio.sleep(0)

    brain.assert_not_awaited()                    # aucune réponse orale
    args, kwargs = feed.record.call_args
    assert "j'ai encore raté mon saut" in args[0]
    assert kwargs["notify"] is False              # perception, pas réveil
    narrator.on_overheard.assert_awaited()        # l'overlay décide seul


@pytest.mark.asyncio
async def test_hors_mode_ecoute_le_cerveau_vocal_repond_toujours():
    """La régression à éviter : casser le vocal Discord normal."""
    svc = _service()
    svc._vc = MagicMock()
    svc.listen_only = False
    with patch("bot.discord.voice.service.handle_transcript", new=AsyncMock()) as brain:
        user = SimpleNamespace(id=42, display_name="Greg", name="greg")
        await svc._dispatch_transcript(user, "salut wally", 100.0)
    brain.assert_awaited()


@pytest.mark.asyncio
async def test_une_transcription_vide_ne_declenche_rien():
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    svc._bot.overlay_narrator = MagicMock()
    with patch("bot.core.stream_feed.active_stream_feed") as feed:
        await svc._dispatch_transcript(SimpleNamespace(id=1), "   ", 0.0)
    feed.assert_not_called()


def test_un_deplacement_manuel_recale_le_salon():
    """Sinon Wally « écoute » un salon qu'il a quitté."""
    svc = _service()
    svc._channel = SimpleNamespace(id=111, name="ancien")
    svc.follow_move(SimpleNamespace(id=222, name="nouveau"))
    assert svc.channel_id == 222


def test_l_absence_d_overlay_ne_casse_pas_l_ecoute():
    svc = _service()
    svc._bot = SimpleNamespace()          # pas d'overlay_narrator
    with patch("bot.core.stream_feed.active_stream_feed", return_value=None):
        svc._observe_transcript("Azrael", "coucou")   # ne doit pas lever


def _demandeur(svc, discord_id="419172225451556874"):
    """Fait du locuteur courant un demandeur déclaré."""
    svc._current_speaker_id = discord_id
    svc._bot.config.voice.requesters = [
        {"discord_id": discord_id, "twitch_login": "azrael_ttv"}
    ]


@pytest.mark.asyncio
async def test_une_demande_en_vocal_part_vers_le_chemin_outille():
    """« Wally, affiche un pile ou face » doit pouvoir AFFICHER — le chemin des
    réactions ne sait que condenser du texte, d'où les trois-points sans suite.

    Depuis 2026-08-08 ce chemin est celui du chat : mêmes outils qu'à l'écrit,
    réponse envoyée dans le chat Twitch."""
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_stream_event = AsyncMock(return_value=None)
    svc._bot.overlay_narrator = narrator
    _demandeur(svc)
    with patch("bot.core.stream_feed.active_stream_feed", return_value=None), \
         patch("bot.discord.voice.request.handle_voice_request",
               new=AsyncMock(return_value=None)) as demande:
        svc._observe_transcript("Azrael", "wally affiche un pile ou face")
        await asyncio.sleep(0)
    demande.assert_awaited()
    narrator.on_stream_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_tiers_en_vocal_est_entendu_mais_pas_obei():
    """Seuls les demandeurs déclarés commandent : les autres restent perçus."""
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_overheard = AsyncMock(return_value=None)
    svc._bot.overlay_narrator = narrator
    svc._current_speaker_id = "999"
    svc._bot.config.voice.requesters = [
        {"discord_id": "419172225451556874", "twitch_login": "azrael_ttv"}
    ]
    with patch("bot.core.stream_feed.active_stream_feed", return_value=None), \
         patch("bot.discord.voice.request.handle_voice_request",
               new=AsyncMock(return_value=None)) as demande:
        svc._observe_transcript("Inconnu", "wally affiche un pile ou face")
        await asyncio.sleep(0)
    demande.assert_not_awaited()
    narrator.on_overheard.assert_awaited()


@pytest.mark.asyncio
async def test_une_phrase_ordinaire_passe_par_la_perception_vocale():
    """Le vocal capte tout : le jeu, les autres. Il ne passe donc PAS par le
    chemin des événements, qui ferait annoncer des raids inexistants — et il
    n'allume pas les trois-points (garanti par `on_overheard`, cf.
    tests/test_overlay_overheard.py)."""
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    narrator = MagicMock()
    narrator.count_spoken_vote.return_value = False
    narrator.on_overheard = AsyncMock(return_value=None)
    narrator.on_stream_event = AsyncMock(return_value=None)
    svc._bot.overlay_narrator = narrator
    with patch("bot.core.stream_feed.active_stream_feed", return_value=None), \
         patch("bot.discord.voice.request.handle_voice_request",
               new=AsyncMock(return_value=None)) as demande:
        svc._observe_transcript("Azrael", "j'ai encore raté mon saut")
        await asyncio.sleep(0)
    demande.assert_not_awaited()
    narrator.on_overheard.assert_awaited()
    narrator.on_stream_event.assert_not_awaited()


# ── retour automatique après un redémarrage ──

@pytest.mark.asyncio
async def test_sortir_d_une_ecoute_pose_un_conge():
    """Sinon le veilleur le ramènerait trente secondes après qu'on l'a fait sortir."""
    svc = _service()
    svc.listen_only = True
    svc._vc = MagicMock()
    svc._vc.disconnect = AsyncMock()
    await svc.leave()
    assert svc.listen_optout is True


@pytest.mark.asyncio
async def test_sortir_d_un_vocal_normal_ne_pose_pas_de_conge():
    svc = _service()
    svc.listen_only = False
    svc._vc = MagicMock()
    svc._vc.disconnect = AsyncMock()
    await svc.leave()
    assert svc.listen_optout is False


@pytest.mark.asyncio
async def test_un_retour_volontaire_leve_le_conge():
    """/ecoute après un /leave doit le rendre à nouveau rattrapable."""
    svc = _service()
    svc.listen_optout = True
    channel = MagicMock()
    channel.connect = AsyncMock(return_value=MagicMock())
    svc._streaming = None
    svc._stt = MagicMock(spec=[])
    with patch("bot.discord.voice.service.WallyAudioSink", MagicMock()):
        await svc.join(channel, listen_only=True)
    assert svc.listen_optout is False
