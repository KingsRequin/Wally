"""Phase 10 : salon de stream écrasé, purge morte, réaction non protégée."""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.voice.service import VoiceService


def _service():
    svc = VoiceService.__new__(VoiceService)
    svc._bot = MagicMock()
    svc._bot.db = MagicMock()
    svc._channel = None
    svc._detached = set()
    svc.listen_only = False
    return svc


# ── Le salon de stream n'est plus écrasé par un `/join` ──────────────────────
#
# `remember_voice_channel` était appelé pour TOUT join — `/join`, l'outil
# `join_voice` (qui rejoint le salon de l'auteur du message), l'auto-join de
# stream. Un « viens en vocal » dans un salon privé écrasait donc durablement le
# salon de stream, et `resolve_voice_channel_id` préférant la base à la config,
# tous les lives suivants y amenaient Wally. Symétriquement, le déplacement à la
# main — le cas que la fonctionnalité visait — n'était jamais retenu.

def test_seul_un_join_decoute_retient_le_salon():
    code = inspect.getsource(VoiceService._join_locked)
    assert "if listen_only:" in code
    assert "self._remember_channel(channel)" in code


def test_un_deplacement_a_la_main_est_retenu():
    """Le cas décrit par `channel_memory` (« on le déplace en cours de
    soirée ») était le seul à ne pas l'être."""
    code = inspect.getsource(VoiceService.follow_move)
    assert "_remember_channel" in code


async def test_remember_channel_ne_leve_jamais():
    svc = _service()
    svc._bot.db = None
    await svc._remember_channel(MagicMock())      # pas de base : silencieux


# ── La file de paroles meurt avec le salon ───────────────────────────────────

def test_leave_vide_la_file_des_paroles_en_attente():
    """Quand `leave()` part de l'INTÉRIEUR de la boucle (« dégage », outil
    `leave_voice`), `_maybe_respond` continuait à défiler : un appel LLM complet
    payé après le départ, puis un `channel_id` None transformé en la chaîne
    « None » comme identifiant de salon."""
    assert "self._pending_queue.clear()" in inspect.getsource(VoiceService.leave)


# ── Le délai d'auto-leave est relu à chaud ───────────────────────────────────

def test_lauto_leave_relit_son_delai_a_chaque_tour():
    """`auto_leave_minutes` est exposé dans le panneau admin, qui appelle
    `reload_config()` — mais le délai n'était lu qu'une fois, avant la boucle."""
    code = inspect.getsource(VoiceService._auto_leave_watch)
    corps_boucle = code.split("while self._vc is not None:")[1]
    assert "self._cfg.auto_leave_minutes" in corps_boucle


def test_le_docstring_de_reload_config_dit_ce_qui_ne_bouge_pas():
    """Il annonçait « seuils » sans réserve, alors que les seuils VAD sont figés
    dans le sink construit au join : on croyait régler à chaud."""
    doc = VoiceService.reload_config.__doc__ or ""
    assert "PROCHAIN JOIN" in doc
    assert "VAD" in doc


# ── Discord : purge du tracker et réaction protégée ──────────────────────────

def test_la_purge_du_tracker_de_spam_nest_plus_un_no_op():
    """`_spam_tracker.pop(key)` était annulé trois lignes plus bas par la
    réinscription de la clé : un no-op, alors que le commentaire annonçait un
    nettoyage. Le dict grossissait d'une entrée par couple (utilisateur, salon)
    pour toute la durée du process."""
    from bot.discord import handlers

    code = inspect.getsource(handlers._check_spam)
    assert "_SPAM_TRACKER_PURGE_AT" in code
    assert "if key not in _spam_tracker:" not in code


async def test_la_colere_monte_meme_sans_permission_de_reagir():
    """C'était le seul `add_reaction` non protégé du fichier. Un
    `discord.Forbidden` remontait hors de `handle_message` et sautait la ligne
    suivante : la colère cessait de monter pendant le mute, comportement pourtant
    documenté, dans tout salon sans cette permission."""
    from bot.discord import handlers

    code = inspect.getsource(handlers.handle_message)
    bloc = code.split("if await bot.db.is_muted(")[1][:1200]
    avant_reaction = bloc[: bloc.index("await message.add_reaction")]
    assert "try:" in avant_reaction                 # la réaction est protégée
    # Le delta est APRÈS le try/except, donc appliqué quoi qu'il arrive.
    assert bloc.index('apply_delta("anger"') > bloc.index("await message.add_reaction")


def test_loffre_et_le_refus_doutils_partagent_la_meme_liste():
    """`image_search` était refusé à l'exécution mais laissé dans l'offre : le
    modèle pouvait l'appeler et ne recevoir qu'un refus parlant d'articles."""
    from bot.discord.handlers import _LOOKUP_TOOLS

    assert "image_search" in _LOOKUP_TOOLS
    assert "web_search" in _LOOKUP_TOOLS
