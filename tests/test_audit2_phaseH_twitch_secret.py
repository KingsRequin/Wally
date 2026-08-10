# tests/test_audit2_phaseH_twitch_secret.py
"""Phase H du second audit : le mot du pendu, et les doubles réponses Twitch.

A2-sg    — `secret_guard` était contourné par une épellation à la VIRGULE.
A2-irc   — les quatre sorties IRC envoyaient le texte brut : le filet ne
           couvrait que la chaîne home via Helix.
A2-spont — l'intervention spontanée Twitch n'était pas exclusive de la réponse
           normale → deux messages pour une seule sollicitation.
A2-notif — `notify_activity` Twitch échouait en silence total.
"""
import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core import secret_guard as sg


# ────────────────────────────── A2-sg ──────────────────────────────
@pytest.mark.parametrize("epellation", [
    "F, L, E, C, H, E",      # la ponctuation la plus naturelle
    "f;l;e;c;h;e",
    "f/l/e/c/h/e",
    "f: l: e: c: h: e",
    "f l e c h e",           # déjà couvert, non-régression
    "f-l-e-c-h-e",
])
def test_le_mot_epelle_est_masque_quelle_que_soit_la_ponctuation(epellation):
    sg.clear_secrets()
    sg.guard_secret("flèche")
    try:
        assert sg.redact(epellation) == "[…]"
    finally:
        sg.clear_secrets()


def test_une_phrase_ordinaire_nest_pas_masquee():
    """Le jeu de séparateurs élargi ne doit pas avaler du texte innocent."""
    sg.clear_secrets()
    sg.guard_secret("flèche")
    try:
        phrase = "je fais le café, lave la vaisselle, et hop"
        assert sg.redact(phrase) == phrase
    finally:
        sg.clear_secrets()


# ────────────────────────────── A2-irc ──────────────────────────────
def test_toutes_les_sorties_twitch_passent_par_le_filet():
    from bot.twitch import handlers

    src = inspect.getsource(handlers._envoyer_reponse_twitch)
    # Redaction AVANT le premier envoi, quel que soit le mode.
    assert src.index("texte = redact(texte)") < src.index("send_message(")


@pytest.mark.asyncio
async def test_le_mot_ne_sort_pas_sur_une_chaine_invitee():
    from bot.twitch.handlers import _envoyer_reponse_twitch

    sg.clear_secrets()
    sg.guard_secret("banane")
    try:
        canal = MagicMock()
        canal.send = AsyncMock()
        bot = MagicMock()
        bot._channel_ids = {"invitee": "42"}
        bot.get_channel = MagicMock(return_value=canal)

        await _envoyer_reponse_twitch(
            bot, "invitee", "le mot c'est banane", author="a", parent_msg_id=None
        )
        envoye = canal.send.await_args.args[0]
        assert "banane" not in envoye
    finally:
        sg.clear_secrets()


def test_les_deux_sorties_annexes_signalent_un_irc_absent():
    """Elles mémorisaient un message jamais parti."""
    from bot.twitch import handlers

    src = inspect.getsource(handlers)
    assert src.count("IRC non connecté pour {ch}, message ignoré") == 2


# ────────────────────────────── A2-spont ──────────────────────────────
def test_le_spontane_twitch_est_exclusif_de_la_reponse():
    from bot.twitch import handlers

    src = inspect.getsource(handlers.handle_message)
    i_trig = src.index("triggered = (bot_nick")
    i_spont = src.index("if not triggered and bot.config.bot.spontaneous_twitch_enabled:")
    assert i_trig < i_spont, "le spontané tourne avant de savoir s'il est interpellé"


# ────────────────────────────── A2-notif ──────────────────────────────
def test_la_perception_cognitive_twitch_ne_se_tait_plus():
    from bot.twitch import handlers

    src = inspect.getsource(handlers.handle_message)
    i = src.index("notify_activity(")
    bloc = src[i:i + 900]
    assert "except Exception:\n            pass" not in bloc
    assert "notify_activity (twitch) en échec" in bloc
