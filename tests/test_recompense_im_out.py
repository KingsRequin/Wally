# tests/test_recompense_im_out.py
"""« im out » : une récompense de points de chaîne qui fait parler Wally (2026-08-20).

Une phrase fixe, dite à voix haute dans le salon vocal. Rien de plus — pas
d'appel au modèle, pas de reformulation : c'est un bouton, pas une conversation.

Comme partout ailleurs sur les points de chaîne, LE REMBOURSEMENT EST LA MOITIÉ
SÉRIEUSE du module : chaque chemin où la phrase ne sort PAS rend les points et
le dit. Hors vocal, Wally n'a pas de bouche — le viewer paierait pour rien.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events import im_out


def _bot(*, connecte=True, speak=None):
    service = MagicMock()
    service.is_connected = connecte
    service.speak = speak or AsyncMock(return_value=True)
    bot = MagicMock()
    bot.discord_bot.voice_service = service
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_message = AsyncMock(return_value=True)
    bot.stream_feed = MagicMock()
    return bot, service


@pytest.mark.asyncio
async def test_la_phrase_sort_a_voix_haute():
    bot, service = _bot()

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    service.speak.assert_awaited_once()
    assert service.speak.call_args.args[0] == im_out.PHRASE
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_elle_passe_malgre_le_mode_ecoute():
    """Pendant un live Wally est en écoute seule et `speak()` refuse de parler.
    C'est justement le moment où cette récompense sert, et l'achat est une
    demande explicite — même raison que `say_in_voice`."""
    bot, service = _bot()

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["malgre_ecoute"] is True


@pytest.mark.asyncio
async def test_hors_vocal_les_points_sont_rendus():
    bot, service = _bot(connecte=False)

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    service.speak.assert_not_awaited()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")
    assert "rendus" in bot.twitch_api.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_une_parole_qui_ne_sort_pas_rembourse():
    """`speak()` rend False quand rien n'a été entendu : le lire est tout
    l'intérêt. Sans ça on encaisse pour un silence."""
    bot, _ = _bot(speak=AsyncMock(return_value=False))

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_une_panne_du_vocal_rembourse_aussi():
    bot, _ = _bot(speak=AsyncMock(side_effect=RuntimeError("azure down")))

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_dit_franchement():
    """Promettre des points qui ne reviendront pas est pire que se taire."""
    bot, _ = _bot(connecte=False)
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await im_out.dire_im_out(bot, acheteur="alice", reward_id="RW", redemption_id="R1")

    texte = bot.twitch_api.send_message.call_args.kwargs["text"]
    assert "PAS pu te rendre tes points" in texte


# ── La récompense est reconnue par son ID, jamais par son titre ───────────

@pytest.mark.asyncio
async def test_l_achat_est_route_vers_le_bon_module(monkeypatch):
    from bot.twitch.events import redemptions

    appels = []

    async def _faux(bot, **kwargs):
        appels.append(kwargs)

    monkeypatch.setattr(im_out, "dire_im_out", _faux)

    bot = MagicMock()
    bot.db.get_state = AsyncMock(
        side_effect=lambda cle: "RW-IMOUT" if cle == im_out.CLE_RECOMPENSE else "")
    event = MagicMock()
    event.reward.id = "RW-IMOUT"
    event.id = "R1"
    event.user.name = "alice"

    await redemptions.handle_redemption(bot, event)

    assert appels and appels[0]["acheteur"] == "alice"


@pytest.mark.asyncio
async def test_sans_id_connu_aucune_recompense_ne_la_declenche():
    """Un ID vide DÉSACTIVE : sinon n'importe quel achat de la chaîne
    ferait parler Wally."""
    from bot.twitch.events.redemptions import _est_le_tts_im_out

    bot = MagicMock()
    bot.db.get_state = AsyncMock(return_value="")

    assert await _est_le_tts_im_out(bot, "RW-IMOUT") is False
