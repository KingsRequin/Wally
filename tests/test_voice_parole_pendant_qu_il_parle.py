"""Parler à Wally PENDANT qu'il parle : sa phrase était jetée, sans une trace.

Symptôme de l'owner (2026-08-30, deuxième passe) : « il ne répond toujours
pas. » Les logs de la session de 06:56 le disent :

    06:56:02  voice: rejoint le salon
    06:56:04  OpenAI — [discord_voice_greeting]        ← il commence à dire bonjour
    06:56:05  énoncé RATTRAPÉ par la soupape (1,4 s)   ← l'owner lui parle
    (rien)

`voice_events` ne porte AUCUN événement `heard` pour cette session : la
transcription n'a jamais atteint `handle_transcript`. Elle est morte dans
`_dispatch_transcript`, sur `if self.is_speaking: return` — un `return` MUET.

Ce garde est le seul filtre anti-larsen : sans casque, la voix de Wally sort
des enceintes, rentre dans le micro de la personne et lui est ATTRIBUÉE ; il
s'entendait alors lui-même, se répondait, et le fact_extractor mémorisait ses
propres phrases comme des faits sur la personne.

Mais il jetait aussi toute VRAIE parole — et Wally parle en arrivant. Répondre
à quelqu'un qui vient de dire bonjour était donc structurellement impossible :
la fenêtre où on lui parle est exactement celle où il n'écoute pas.

Le discriminant n'est pas le silence, c'est le CONTENU : on sait mot pour mot
ce que Wally est en train de dire. Ce qui lui ressemble est un écho ; le reste
est quelqu'un qui parle, et le doute profite au locuteur.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.discord.voice.brain import est_un_echo
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
        svc = VoiceService(bot, cfg)
    svc._vc = MagicMock()
    svc._channel = SimpleNamespace(id=7, name="Général", members=[])
    return svc


# ── Le discriminant, seul ────────────────────────────────────────────────────

@pytest.mark.parametrize("entendu", [
    "Salut vous faites quoi de beau",          # l'écho intégral
    "vous faites quoi",                        # le STT n'en attrape qu'un bout
    "salut, vous faites quoi de beau ?",       # ponctuation et casse en plus
])
def test_ce_qui_revient_de_ses_propres_enceintes_est_un_echo(entendu):
    assert est_un_echo(entendu, "Salut, vous faites quoi de beau ?")


@pytest.mark.parametrize("entendu", [
    "ouais je suis là tranquille",
    "attends deux secondes je reviens",
    "non mais franchement c'est pas beau",     # « beau » en commun, rien de plus
])
def test_une_vraie_phrase_n_est_pas_un_echo(entendu):
    assert not est_un_echo(entendu, "Salut, vous faites quoi de beau ?")


def test_sans_savoir_ce_qu_il_dit_rien_n_est_un_echo():
    """Le doute profite au locuteur : jeter sa phrase est le défaut qu'on corrige."""
    assert not est_un_echo("vous faites quoi", "")


# ── L'aiguillage réel ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_lui_parle_pendant_son_bonjour_et_il_entend():
    svc = _service()
    svc.is_speaking = True
    svc._texte_parle = "Salut, vous faites quoi de beau ?"
    user = SimpleNamespace(id=42, display_name="KingsRequin", name="kingsrequin")
    with patch("bot.discord.voice.service.handle_transcript",
               new=AsyncMock()) as cerveau:
        await svc._dispatch_transcript(user, "ouais je suis là tranquille", 120.0)
    cerveau.assert_awaited_once()
    assert cerveau.await_args.kwargs["transcript"] == "ouais je suis là tranquille"


@pytest.mark.asyncio
async def test_sa_propre_voix_reinjectee_ne_lui_revient_pas():
    svc = _service()
    svc.is_speaking = True
    svc._texte_parle = "Salut, vous faites quoi de beau ?"
    user = SimpleNamespace(id=42, display_name="KingsRequin", name="kingsrequin")
    with patch("bot.discord.voice.service.handle_transcript",
               new=AsyncMock()) as cerveau:
        await svc._dispatch_transcript(user, "salut vous faites quoi de beau", 120.0)
    cerveau.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_ordre_d_arret_le_coupe_toujours():
    """Le barge-in ne passe pas par le cerveau : il coupe la lecture sur place."""
    svc = _service()
    svc.is_speaking = True
    svc._texte_parle = "Salut, vous faites quoi de beau ?"
    svc.stop_speaking = MagicMock()
    user = SimpleNamespace(id=42, display_name="KingsRequin", name="kingsrequin")
    with patch("bot.discord.voice.service.handle_transcript",
               new=AsyncMock()) as cerveau:
        await svc._dispatch_transcript(user, "stop", 120.0)
    svc.stop_speaking.assert_called_once()
    cerveau.assert_not_awaited()


@pytest.mark.asyncio
async def test_ce_qu_il_dit_est_su_pendant_qu_il_le_dit():
    """`_texte_parle` est posé par le chemin réel, et effacé après.

    Sans ça le discriminant n'a rien à comparer, `est_un_echo` rend toujours
    Faux, et sa propre voix lui revient — le défaut d'avant le garde.
    """
    svc = _service()
    vu: list[str] = []

    async def fausse_lecture(text, style, *a):
        vu.append(svc._texte_parle)
        return True

    svc._tts = MagicMock(spec=[])          # pas de `synthesize_stream` → chemin batch
    svc.quota = MagicMock()
    with patch.object(VoiceService, "_speak_batch", new=fausse_lecture), \
         patch("bot.discord.voice.service.resolve_style",
               lambda t, *a, **k: (None, t)), \
         patch("bot.discord.voice.service.POST_SPEAK_MUTE_S", 0):
        await svc.speak("Salut, vous faites quoi de beau ?")
    assert vu == ["Salut, vous faites quoi de beau ?"]
    assert svc._texte_parle == ""          # effacé : plus rien à comparer après
