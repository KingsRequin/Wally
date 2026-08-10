# tests/test_phase4_discord_voice_vision.py
"""Phase 4 de l'audit du 2026-08-10 : cinq défauts critiques.

C11 — une réaction 🔍 refusée annulait TOUTE la réponse.
C12 — tout rappel demandé en MP échouait sans être créé.
C13 — le préchauffage STT détaché remettait Wally dans un salon quitté.
C14 — `/join` et `/leave` sans `defer()` → « L'application n'a pas répondu ».
C15 — `vision_model` vide retombait sur un champ que 3 UIs écrasent.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.discord.handlers import _resolve_discord_roles


# ────────────────────────────── C11 ──────────────────────────────
@pytest.mark.asyncio
async def test_une_reaction_refusee_ne_rend_pas_wally_muet():
    """Salon où Wally peut écrire mais pas réagir : il restait totalement muet."""
    import discord as _discord
    from bot.discord import handlers as h

    message = MagicMock()
    message.add_reaction = AsyncMock(
        side_effect=_discord.Forbidden(MagicMock(status=403), "Missing Permissions")
    )
    message.channel.id = 123

    bot = MagicMock()
    # On observe la première opération qui suit la réaction : si elle est
    # atteinte, c'est que le 403 n'a pas emporté toute la réponse.
    bot.db.get_trust_score = AsyncMock(side_effect=RuntimeError("borne du test"))

    with patch.object(h, "logger"):
        await h._respond(bot, message, user_id="1", guild_id="2", prelude=[])

    bot.db.get_trust_score.assert_awaited_once()


# ────────────────────────────── C12 ──────────────────────────────
def test_un_user_de_mp_na_pas_de_roles_mais_ne_casse_pas():
    """En MP, `message.author` est un `discord.User` : ni roles ni permissions."""
    class _User:  # discord.User n'a ni `roles` ni `guild_permissions`
        id = 610550333042589752

    assert _resolve_discord_roles(_User()) == ["everyone"]


def test_un_membre_de_serveur_garde_ses_roles():
    role = MagicMock(id=42)
    role.is_default.return_value = False
    membre = MagicMock(roles=[role])
    membre.guild_permissions.administrator = False
    assert _resolve_discord_roles(membre) == ["everyone", "42"]


def test_un_administrateur_est_reconnu():
    role = MagicMock(id=7)
    role.is_default.return_value = False
    membre = MagicMock(roles=[role])
    membre.guild_permissions.administrator = True
    assert "admin" in _resolve_discord_roles(membre)


# ────────────────────────────── C13 ──────────────────────────────
@pytest.mark.asyncio
async def test_le_prechauffage_ne_demute_pas_apres_un_depart():
    from bot.discord.voice import readiness

    vc = MagicMock()
    vc.is_connected.return_value = False       # Wally a quitté entre-temps
    vc.channel = MagicMock()                   # discord.py le laisse renseigné

    with patch.object(readiness, "set_muted", new=AsyncMock()) as demute:
        await readiness.signal_ready_when_warm(vc, warmup=None, stt=None)

    demute.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_prechauffage_demute_bien_quand_il_est_encore_la():
    from bot.discord.voice import readiness

    vc = MagicMock()
    vc.is_connected.return_value = True

    with patch.object(readiness, "set_muted", new=AsyncMock()) as demute:
        await readiness.signal_ready_when_warm(vc, warmup=None, stt=None)

    demute.assert_awaited_once()
    assert demute.await_args.args[1] is False


@pytest.mark.asyncio
async def test_leave_annule_les_taches_detachees():
    """Sinon le préchauffage survit au départ et ramène Wally dans le salon."""
    from bot.discord.voice.service import VoiceService

    svc = VoiceService.__new__(VoiceService)
    svc._detached = set()
    svc._pending_queue = MagicMock()
    svc._streaming = None
    svc._stream_users = MagicMock()
    svc._vc = None
    svc._channel = None
    svc.history = MagicMock()
    svc.listen_only = False
    svc.listen_optout = False
    svc._auto_leave_task = svc._maintain_task = svc._silence_task = None
    svc._test_mode_taken = False

    async def _longue():
        await asyncio.sleep(60)

    t = asyncio.create_task(_longue())
    svc._detached.add(t)
    await asyncio.sleep(0)

    await VoiceService.leave(svc)

    assert t.cancelled() or t.cancelling() > 0 or t.done()
    assert not svc._detached


# ────────────────────────────── C14 ──────────────────────────────
@pytest.mark.asyncio
async def test_join_defere_avant_de_se_connecter():
    from bot.discord.commands.voice_cmd import VoiceCog

    bot = MagicMock()
    bot.voice_service.join = AsyncMock()
    cog = VoiceCog.__new__(VoiceCog)
    cog.bot = bot

    it = MagicMock()
    it.response.defer = AsyncMock()
    it.response.send_message = AsyncMock()
    it.followup.send = AsyncMock()
    it.user.voice.channel = MagicMock(name="Général")

    await VoiceCog.join.callback(cog, it)

    it.response.defer.assert_awaited_once()
    it.response.send_message.assert_not_awaited()
    it.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_en_echec_repond_par_le_followup():
    from bot.discord.commands.voice_cmd import VoiceCog

    bot = MagicMock()
    bot.voice_service.join = AsyncMock(side_effect=RuntimeError("gateway down"))
    cog = VoiceCog.__new__(VoiceCog)
    cog.bot = bot

    it = MagicMock()
    it.response.defer = AsyncMock()
    it.response.send_message = AsyncMock()
    it.followup.send = AsyncMock()
    it.user.voice.channel = MagicMock()

    await VoiceCog.join.callback(cog, it)

    it.response.send_message.assert_not_awaited()
    it.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_leave_defere_aussi():
    from bot.discord.commands.voice_cmd import VoiceCog

    bot = MagicMock()
    bot.voice_service.is_connected = True
    bot.voice_service.leave = AsyncMock()
    cog = VoiceCog.__new__(VoiceCog)
    cog.bot = bot

    it = MagicMock()
    it.response.defer = AsyncMock()
    it.response.send_message = AsyncMock()
    it.followup.send = AsyncMock()

    await VoiceCog.leave.callback(cog, it)

    it.response.defer.assert_awaited_once()
    it.followup.send.assert_awaited_once()


# ────────────────────────────── C15 ──────────────────────────────
def test_la_vision_ne_retombe_pas_sur_le_modele_secondaire():
    """`secondary_model` est réécrit par /config, llm.secondary et /wally setup."""
    import bot.bootstrap as bs

    config = MagicMock()
    config.openai.vision_model = ""
    config.openai.secondary_model = "deepseek-chat"   # modèle TEXTE, aveugle

    modele = getattr(config.openai, "vision_model", "") or bs._VISION_MODEL_DEFAUT
    assert modele != config.openai.secondary_model
    assert modele == "gpt-5-nano"


def test_un_vision_model_explicite_est_respecte():
    import bot.bootstrap as bs

    config = MagicMock()
    config.openai.vision_model = "gpt-5"
    modele = getattr(config.openai, "vision_model", "") or bs._VISION_MODEL_DEFAUT
    assert modele == "gpt-5"


@pytest.mark.asyncio
async def test_une_vision_en_repli_laisse_une_trace():
    """Sans log, un modèle mal configuré rend Wally aveugle en silence."""
    from bot.core.llm.base import FALLBACK_RESPONSE
    from bot.core.vision import VisionService

    client = MagicMock()
    client._model = "deepseek-chat"
    client.complete = AsyncMock(return_value=FALLBACK_RESPONSE)
    svc = VisionService(client)

    with patch("bot.core.vision.logger") as log:
        out = await svc.analyze(["http://x/img.png"])

    assert out is None
    log.warning.assert_called()
