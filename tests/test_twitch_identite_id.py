"""L'identité d'un Twitcheur, c'est son ID — jamais son pseudo.

Un login Twitch se change quand on veut ; l'identifiant numérique, jamais.
Toute clé bâtie sur le pseudo produit un second dossier le jour où quelqu'un se
renomme, sans que rien ne le signale : les deux existent, aucun ne se plaint.

`handlers.py` le dit déjà en toutes lettres (« le login change, l'ID non, et
deux formes de clé rendent les coûts inagrégeables ») et le respecte partout.
Les événements sociaux, eux, y échappaient — relevé le 2026-08-28 dans
`cost_log` : 31 clés-pseudo pour 50 clés-ID.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.twitch.events.social import _generate_and_send


def _bot():
    bot = MagicMock()
    bot.llm.complete = AsyncMock(return_value="bienvenue")
    bot.twitch_api.send_automatic = AsyncMock(return_value=True)
    bot.emotion.get_state = MagicMock(return_value={})
    bot.prompts.build_system_prompt = MagicMock(return_value="système")
    bot._channel_ids = {}
    return bot


@pytest.mark.asyncio
async def test_l_evenement_social_facture_sur_l_ID_pas_sur_le_pseudo():
    bot = _bot()
    await _generate_and_send(bot, "azrael_ttv", "{username} a follow",
                             username="Kassandre", user_id="123456")

    assert bot.llm.complete.await_args.kwargs["user_id"] == "twitch:123456"


@pytest.mark.asyncio
async def test_sans_identifiant_on_ne_facture_a_PERSONNE():
    """Un cheer anonyme n'a pas d'utilisateur. Se rabattre sur le pseudo
    recréerait exactement la clé qu'on vient de retirer — mieux vaut ne rien
    attribuer que d'attribuer à une chaîne de caractères."""
    bot = _bot()
    await _generate_and_send(bot, "azrael_ttv", "{username} a cheer",
                             username="Anonyme", user_id="")

    assert bot.llm.complete.await_args.kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_le_pseudo_reste_donne_au_modele():
    """L'ID sert de CLÉ, pas de nom : Wally doit continuer d'appeler la personne
    par son pseudo. Séparer les deux est tout l'enjeu — l'un identifie,
    l'autre s'adresse."""
    bot = _bot()
    await _generate_and_send(bot, "azrael_ttv", "{username} a follow",
                             username="Kassandre", user_id="123456")

    dit = bot.llm.complete.await_args.args[1][0]["content"]
    assert "Kassandre" in dit
