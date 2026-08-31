# tests/test_recompense_tts_viewer.py
"""Le TTS des viewers : on paie, Wally lit le message à voix haute (2026-08-31).

Cousine de « im out », à ceci près que le texte vient du viewer. Ce qui s'y
joue en plus : le message ne pilote PAS la voix (les tags entre crochets sont
retirés), il est plafonné, le pseudo est dit, et un message vidé par le
nettoyage rend les points au lieu de partir mourir dans `_speak_locked`.

Comme partout ailleurs sur les points de chaîne, LE REMBOURSEMENT EST LA MOITIÉ
SÉRIEUSE du module : chaque chemin où le message ne sort PAS rend les points et
le dit.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events import tts_viewer


def _bot(*, connecte=True, speak=None):
    service = MagicMock()
    service.is_connected = connecte
    service.speak = speak or AsyncMock(return_value=True)
    bot = MagicMock()
    bot.discord_bot.voice_service = service
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    bot.stream_feed = MagicMock()
    return bot, service


@pytest.mark.asyncio
async def test_le_message_du_viewer_sort_a_voix_haute():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="salut les gens",
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "salut les gens" in dit
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_pseudo_de_l_acheteur_est_prononce():
    """Un TTS anonyme ne s'attribue à personne : ceux du vocal entendraient
    une phrase surgie de nulle part dans la bouche de Wally."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="coucou",
                                  reward_id="RW", redemption_id="R1")

    assert "alice" in service.speak.call_args.args[0]


@pytest.mark.asyncio
async def test_les_tags_de_style_ne_pilotent_pas_la_voix():
    """`[murmure]` est le langage de commande de `resolve_style` : laissé
    passer, c'est le viewer qui choisit le ton de Wally."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[colère] bonjour",
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "[" not in dit and "colère" not in dit
    assert "bonjour" in dit


@pytest.mark.asyncio
async def test_un_message_qui_n_est_QUE_des_tags_rembourse():
    """Sans ce garde, il serait vidé bien plus loin, dans `_speak_locked`, où
    plus personne ne sait qu'il y avait des points à rendre."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="[murmure]",
                                  reward_id="RW", redemption_id="R1")

    service.speak.assert_not_awaited()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_le_message_est_plafonne():
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="a" * 500,
                                  reward_id="RW", redemption_id="R1")

    dit = service.speak.call_args.args[0]
    assert "a" * tts_viewer.LONGUEUR_MAX in dit
    assert "a" * (tts_viewer.LONGUEUR_MAX + 1) not in dit


@pytest.mark.asyncio
async def test_elle_passe_malgre_le_mode_ecoute():
    """Pendant un live Wally est en écoute seule ; l'achat est une demande
    explicite — même arbitrage que « im out »."""
    bot, service = _bot()

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert service.speak.call_args.kwargs["malgre_ecoute"] is True


@pytest.mark.asyncio
async def test_hors_vocal_les_points_sont_rendus():
    bot, service = _bot(connecte=False)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    service.speak.assert_not_awaited()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")
    assert "rendus" in bot.twitch_api.send_automatic.call_args.args[0]


@pytest.mark.asyncio
async def test_une_parole_qui_ne_sort_pas_rembourse():
    bot, _ = _bot(speak=AsyncMock(return_value=False))

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_une_panne_du_vocal_rembourse_aussi():
    bot, _ = _bot(speak=AsyncMock(side_effect=RuntimeError("azure down")))

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("RW", "R1")


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_dit_franchement():
    bot, _ = _bot(connecte=False)
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await tts_viewer.lire_message(bot, acheteur="alice", saisie="hello",
                                  reward_id="RW", redemption_id="R1")

    assert "PAS pu te rendre tes points" in bot.twitch_api.send_automatic.call_args.args[0]


# ── La récompense est reconnue par son ID, jamais par son titre ───────────

@pytest.mark.asyncio
async def test_l_achat_est_route_vers_le_bon_module(monkeypatch):
    from bot.twitch.events import redemptions

    appels = []

    async def _faux(bot, **kwargs):
        appels.append(kwargs)

    monkeypatch.setattr(tts_viewer, "lire_message", _faux)

    bot = MagicMock()
    bot.db.get_state = AsyncMock(
        side_effect=lambda cle: "RW-TTS" if cle == tts_viewer.CLE_RECOMPENSE else "")
    event = MagicMock()
    event.reward.id = "RW-TTS"
    event.id = "R1"
    event.user.name = "alice"
    event.input = "coucou"

    await redemptions.handle_redemption(bot, event)

    assert appels and appels[0]["acheteur"] == "alice"
    assert appels[0]["saisie"] == "coucou"


@pytest.mark.asyncio
async def test_sans_id_connu_aucune_recompense_ne_la_declenche():
    """Un ID vide DÉSACTIVE : sinon n'importe quel achat de la chaîne ferait
    lire sa saisie à voix haute."""
    from bot.twitch.events import redemptions

    bot = MagicMock()
    bot.db.get_state = AsyncMock(return_value="")

    assert await redemptions._est_le_tts_viewer(bot, "RW-AUTRE") is False
