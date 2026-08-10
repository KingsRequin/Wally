# tests/test_phase11_discord_vocal.py
"""Phase 11 de l'audit du 2026-08-10 : Discord et vocal.

M27 — la parole spontanée ne passait ni par `redact` ni par le découpage.
M28 — le chemin réaction ignorait le filtrage par canal.
M29 — `_is_leave_request` était testé AVANT de vérifier que Wally est nommé :
      il quittait le vocal sur une phrase adressée à quelqu'un d'autre.
M30 — `/wally ask` perdait toute réponse de plus de 2 000 caractères.
M43 — `create_task` sans référence forte sur le post-traitement vocal.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.discord.handlers import _is_channel_allowed


# ────────────────────────────── M29 ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", [
    "putain dégage",                       # lancé à un ennemi en jeu
    "casse toi de mon écran",
    "je me déconnecte deux minutes",
    "vas-y dégage lui",
])
async def test_il_ne_quitte_pas_le_vocal_sans_etre_nomme(phrase):
    from bot.discord.voice import brain

    service = MagicMock()
    service.leave = AsyncMock()
    service.speak = AsyncMock()
    service.history = []
    bot = MagicMock()
    bot.config.bot.name = "Wally"
    bot.config.bot.trigger_names = []

    await brain._respond_once(bot, service, "1", "Azraël", phrase)
    service.leave.assert_not_awaited()


@pytest.mark.asyncio
async def test_il_quitte_bien_quand_on_le_lui_demande():
    from bot.discord.voice import brain

    service = MagicMock()
    service.leave = AsyncMock()
    service.speak = AsyncMock()
    service.history = []
    bot = MagicMock()
    bot.config.bot.name = "Wally"
    bot.config.bot.trigger_names = []

    await brain._respond_once(bot, service, "1", "Azraël", "wally tu peux nous laisser")
    service.leave.assert_awaited_once()


def test_le_depart_est_teste_apres_la_nomination():
    from bot.discord.voice import brain

    src = inspect.getsource(brain._respond_once_inner)
    assert src.index("named = _is_named(") < src.index("if named and _is_leave_request(")


# ────────────────────────────── M43 ──────────────────────────────
def test_le_post_traitement_vocal_garde_une_reference():
    from bot.discord.voice import brain

    src = inspect.getsource(brain._respond_once_inner)
    assert "_TACHES_FOND.add(tache)" in src
    assert "asyncio.create_task(_voice_post_emotion(" in src


# ────────────────────────────── M28 ──────────────────────────────
def test_une_reaction_dans_un_salon_exclu_est_ignoree():
    config = MagicMock()
    config.discord.per_guild_channel_whitelist = {}
    config.discord.channel_filter_mode = "blacklist"
    config.discord.channel_blacklist = [999]
    assert _is_channel_allowed(config, 999, 1) is False
    assert _is_channel_allowed(config, 111, 1) is True


def test_le_chemin_reaction_applique_bien_le_filtre():
    from bot.discord import handlers

    src = inspect.getsource(handlers._reactions_context)
    assert "_is_channel_allowed(bot.config, payload.channel_id, payload.guild_id)" in src


# ────────────────────────────── M27 ──────────────────────────────
def test_la_parole_spontanee_est_filtree_et_decoupee():
    from bot.discord import handlers

    src = inspect.getsource(handlers._spontaneous_respond)
    assert "reply = redact(reply)" in src
    assert "split_for_discord(reply)" in src
    # Le compte de parts remonte au journal de conversation.
    assert "parts=len(parts)" in src


# ────────────────────────────── M30 ──────────────────────────────
def test_ask_decoupe_ses_reponses():
    from bot.discord.commands import ask

    src = inspect.getsource(ask)
    assert "for part in split_for_discord(reply):" in src


def test_le_decoupage_respecte_la_limite_discord():
    from bot.discord.message_split import split_for_discord

    parts = split_for_discord("x" * 5000)
    assert len(parts) > 1
    assert all(len(p) <= 2000 for p in parts)
