"""Sur une chaîne invitée, Wally doit RÉPONDRE, pas préfixer un pseudo.

Constaté par l'owner le 2026-08-09, après avoir fait venir Wally sur la chaîne de
potitewonder : ses messages arrivaient en « @pseudo texte » au lieu d'utiliser la
fonction de réponse de Twitch. Sur la chaîne home il répond correctement (Helix, avec
`reply_parent_message_id`) ; le chemin invité passait par IRC et le commentaire du
code l'assumait — « mention @author pour SIMULER une réponse ».

Twitch sait pourtant chaîner une réponse en IRC, via le tag `@reply-parent-msg-id`
sur le PRIVMSG. C'est twitchio 2 qui ne l'expose pas : la demande est ouverte depuis
2020 (PythonistaGuild/TwitchIO#119). On écrit donc le PRIVMSG taggé nous-mêmes, en
gardant les garde-fous de `Channel.send` — validation du contenu et rate-limiter IRC,
dont le contournement expose à un ban.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.twitch.handlers import _envoyer_reponse_twitch


def _bot(*, invitee=True, avec_ws=True):
    bot = MagicMock()
    bot._channel_ids = {"potitewonder": "42"} if invitee else {}
    bot.twitch_api.send_message = AsyncMock()
    canal = MagicMock()
    canal.check_content = MagicMock()
    canal.check_bucket = MagicMock()
    canal.send = AsyncMock()
    canal._fetch_websocket = MagicMock(return_value=MagicMock(send=AsyncMock()) if avec_ws else None)
    bot.get_channel = MagicMock(return_value=canal)
    return bot, canal


@pytest.mark.asyncio
async def test_sur_chaine_invitee_la_reponse_est_chainee():
    bot, canal = _bot()

    mode = await _envoyer_reponse_twitch(
        bot, "potitewonder", "salut, ça va ?", author="viewer", parent_msg_id="abc-123"
    )

    assert mode == "irc_reply"
    ws = canal._fetch_websocket.return_value
    (envoye,), _ = ws.send.call_args
    assert envoye.startswith("@reply-parent-msg-id=abc-123 PRIVMSG #potitewonder :")
    assert "salut, ça va ?" in envoye
    assert envoye.endswith("\r\n")
    # Plus de préfixe « @pseudo » : c'est le fil de réponse qui porte l'adressage.
    assert "@viewer" not in envoye
    canal.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_les_garde_fous_de_twitchio_sont_conserves():
    """Contourner le rate-limiter IRC expose à un ban : on le sollicite quand même."""
    bot, canal = _bot()

    await _envoyer_reponse_twitch(
        bot, "potitewonder", "coucou", author="viewer", parent_msg_id="abc"
    )

    canal.check_content.assert_called_once()
    canal.check_bucket.assert_called_once_with(channel="potitewonder")


@pytest.mark.asyncio
async def test_sans_id_de_message_on_retombe_sur_la_mention():
    """Un message sans id ne peut pas être chaîné — mieux vaut la mention que rien."""
    bot, canal = _bot()

    mode = await _envoyer_reponse_twitch(
        bot, "potitewonder", "coucou", author="viewer", parent_msg_id=None
    )

    assert mode == "irc_mention"
    canal.send.assert_awaited_once_with("@viewer coucou")


@pytest.mark.asyncio
async def test_un_websocket_absent_retombe_sur_la_mention():
    bot, canal = _bot(avec_ws=False)

    mode = await _envoyer_reponse_twitch(
        bot, "potitewonder", "coucou", author="viewer", parent_msg_id="abc"
    )

    assert mode == "irc_mention"
    canal.send.assert_awaited_once_with("@viewer coucou")


@pytest.mark.asyncio
async def test_la_chaine_home_passe_toujours_par_helix():
    """Le chemin home fonctionnait : ne pas le changer."""
    bot, _ = _bot(invitee=False)

    mode = await _envoyer_reponse_twitch(
        bot, "azrael_ttv", "coucou", author="viewer", parent_msg_id="abc"
    )

    assert mode == "helix"
    bot.twitch_api.send_message.assert_awaited_once_with(
        text="coucou", reply_parent_message_id="abc"
    )


@pytest.mark.asyncio
async def test_irc_deconnecte_ne_leve_pas():
    bot, _ = _bot()
    bot.get_channel = MagicMock(return_value=None)

    assert await _envoyer_reponse_twitch(
        bot, "potitewonder", "coucou", author="viewer", parent_msg_id="abc"
    ) == "perdu"
