"""L'avalanche de memes s'achète 50 000 points de chaîne.

Second volet du §9. L'effet visuel existe (`meme_storm`) ; il s'agit ici de le
vendre, et surtout de RENDRE LES POINTS quand il ne peut pas être livré.

🚨 Twitch réserve le remboursement d'une redemption à l'application qui a CRÉÉ
la récompense — une récompense posée à la main dans la console est
irremboursable (403). Wally la crée donc lui-même, et son identifiant est
découvert à l'exécution, jamais écrit en configuration. Même règle que le duel,
et c'est pour ça que les deux partagent `bot/twitch/recompenses.py`.

Le remboursement est la partie qui compte : 50 000 points, c'est cher. Chaque
chemin où l'avalanche ne tombe pas doit rendre les points ET le dire.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.events.avalanche import CLE_RECOMPENSE, lancer_avalanche


def _bot(*, narrateur=True, live=True, storm_ok=True):
    bot = MagicMock()
    bot.twitch_api.refund_redemption = AsyncMock(return_value=True)
    bot.twitch_api.send_message = AsyncMock()
    if narrateur:
        narrateur_obj = MagicMock()
        narrateur_obj.is_active.return_value = live
        narrateur_obj.show_meme_storm.return_value = storm_ok
        bot.discord_bot.overlay_narrator = narrateur_obj
    else:
        bot.discord_bot.overlay_narrator = None
    return bot


@pytest.mark.asyncio
async def test_l_avalanche_tombe_et_les_points_restent_depenses():
    bot = _bot()
    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    bot.discord_bot.overlay_narrator.show_meme_storm.assert_called_once()
    bot.twitch_api.refund_redemption.assert_not_awaited()


@pytest.mark.asyncio
async def test_hors_live_les_points_sont_rendus():
    """Il n'y a pas d'écran à submerger : garder 50 000 points pour un
    spectacle que personne ne verra serait du vol."""
    bot = _bot(live=False)
    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    bot.discord_bot.overlay_narrator.show_meme_storm.assert_not_called()
    bot.twitch_api.refund_redemption.assert_awaited_once_with("r1", "d1")
    dit = bot.twitch_api.send_message.await_args.kwargs["text"].lower()
    assert "rina" in dit and ("rendu" in dit or "remboursé" in dit)


@pytest.mark.asyncio
async def test_sans_overlay_les_points_sont_rendus():
    """Overlay non câblé (Discord down, boot partiel) : même règle."""
    bot = _bot(narrateur=False)
    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("r1", "d1")


@pytest.mark.asyncio
async def test_un_refus_de_l_overlay_rend_les_points():
    """`show_meme_storm` peut refuser (écran éteint entre-temps). Son retour
    est LU — sans ça, on annoncerait une avalanche qui n'a pas eu lieu."""
    bot = _bot(storm_ok=False)
    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("r1", "d1")


@pytest.mark.asyncio
async def test_une_panne_pendant_le_lancement_rend_les_points():
    """Le filet : une exception ne doit pas coûter 50 000 points au viewer."""
    bot = _bot()
    bot.discord_bot.overlay_narrator.show_meme_storm.side_effect = RuntimeError("bus mort")

    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    bot.twitch_api.refund_redemption.assert_awaited_once_with("r1", "d1")


@pytest.mark.asyncio
async def test_un_remboursement_refuse_est_dit_tel_quel():
    """Twitch peut refuser le remboursement. Promettre des points qui ne
    reviendront pas est pire que de ne rien promettre."""
    bot = _bot(live=False)
    bot.twitch_api.refund_redemption = AsyncMock(return_value=False)

    await lancer_avalanche(bot, acheteur="rina", reward_id="r1", redemption_id="d1")

    dit = bot.twitch_api.send_message.await_args.kwargs["text"].lower()
    assert "rendre" in dit or "manuellement" in dit or "pas pu" in dit


def test_la_cle_d_etat_est_distincte_de_celle_du_duel():
    """Partager la clé ferait pointer les deux récompenses sur le même
    identifiant : l'une deviendrait irremboursable, l'autre lancerait un duel
    pour une avalanche."""
    from bot.core.apex.duel_runner import CLE_RECOMPENSE as CLE_DUEL

    assert CLE_RECOMPENSE != CLE_DUEL
