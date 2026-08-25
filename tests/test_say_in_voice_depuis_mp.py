"""L'owner doit pouvoir faire parler Wally à voix haute depuis un MP.

Demandé par l'owner le 2026-08-25 : « je veux pouvoir le faire parler en vocal
via MP quand il est en mode écoute, comme via le chat Twitch ».

`say_in_voice` existait, réservé au chat Twitch au motif que l'autorisation se
lit sur un badge de modérateur. Le piège est dans `_resolve_discord_roles` : en
message privé, `message.author` est un `discord.User` — ni `roles`, ni
`guild_permissions` — et la fonction rend `["everyone"]`. L'owner, qui écrit
surtout en MP, se voyait donc refuser un pouvoir qu'il a plus que quiconque.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import _roles_discord_effectifs
from bot.discord.voice.tools import run_say_in_voice_tool


def _bot(owner="42", admins=()):
    bot = MagicMock()
    bot.config = SimpleNamespace(
        bot=SimpleNamespace(owner_discord_id=owner),
        admin_ids=list(admins),
    )
    return bot


def _en_mp(uid):
    """`discord.User` : pas de `roles`, pas de `guild_permissions`."""
    return SimpleNamespace(id=uid)


# ── la résolution des droits ───────────────────────────────────────────
def test_l_owner_est_admin_meme_en_MP():
    roles = _roles_discord_effectifs(_bot(owner="42"), _en_mp(42))
    assert "admin" in roles, (
        "en MP `_resolve_discord_roles` rend ['everyone'] — sans la couche "
        "config, l'owner est traité comme un inconnu dans son propre MP"
    )


def test_un_admin_declare_en_config_aussi():
    roles = _roles_discord_effectifs(_bot(owner="42", admins=["77"]), _en_mp(77))
    assert "admin" in roles


def test_un_inconnu_en_MP_reste_un_inconnu():
    roles = _roles_discord_effectifs(_bot(owner="42"), _en_mp(999))
    assert "admin" not in roles
    assert roles == ["everyone"]


def test_un_admin_de_GUILDE_garde_son_droit():
    """La couche config s'AJOUTE, elle ne remplace pas la lecture des rôles."""
    membre = MagicMock()
    membre.id = 555
    role = MagicMock()
    role.id = 900
    role.is_default = MagicMock(return_value=False)
    membre.roles = [role]
    membre.guild_permissions = SimpleNamespace(administrator=True)

    roles = _roles_discord_effectifs(_bot(owner="42"), membre)
    assert "admin" in roles
    assert "900" in roles
    assert roles.count("admin") == 1, "le rôle a été ajouté deux fois"


# ── le pouvoir lui-même ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_l_owner_fait_VRAIMENT_parler_wally_depuis_un_MP():
    # Sur le chemin DISCORD, `bot` EST le bot Discord : il porte `voice_service`
    # directement. `bot.discord_bot` est la référence CROISÉE, qui n'existe que
    # sur le bot Twitch. Poser `discord_bot` ici calquerait le chemin Twitch et
    # figerait le défaut vécu le 2026-08-25 — « je ne suis plus dans le salon
    # vocal » répondu alors que Wally y était.
    bot = _bot(owner="42")
    service = MagicMock()
    service.is_connected = True
    service.speak = AsyncMock(return_value="Salut à tous")
    bot.voice_service = service
    bot.discord_bot = None

    rendu = await run_say_in_voice_tool(
        bot, {"text": "Salut à tous"},
        roles=_roles_discord_effectifs(bot, _en_mp(42)), maison=True)

    service.speak.assert_awaited_once()
    # `malgre_ecoute` est CE qui permet de parler pendant un live, où Wally est
    # en écoute seule et se tait pour ne pas couvrir le streamer. C'est
    # exactement le moment demandé : « quand il est en mode écoute ».
    assert service.speak.await_args.kwargs.get("malgre_ecoute") is True
    assert "à voix haute" in rendu


@pytest.mark.asyncio
async def test_un_inconnu_en_MP_se_fait_refuser():
    bot = _bot(owner="42")
    service = MagicMock()
    service.is_connected = True
    service.speak = AsyncMock(return_value="x")
    bot.voice_service = service
    bot.discord_bot = None

    rendu = await run_say_in_voice_tool(
        bot, {"text": "coucou"},
        roles=_roles_discord_effectifs(bot, _en_mp(999)), maison=True)

    assert not service.speak.called, "un inconnu a fait parler Wally en vocal"
    assert rendu.startswith("Refusé")


@pytest.mark.asyncio
async def test_le_service_vocal_est_trouve_DES_DEUX_COTES():
    """Vécu le 2026-08-25 : « je ne suis plus dans le salon vocal actuellement »,
    alors que Wally y était bel et bien.

    `run_say_in_voice_tool` ne cherchait le service que sur `bot.discord_bot` —
    la référence CROISÉE, posée sur le bot TWITCH. Depuis un MP Discord, `bot`
    est déjà le bot Discord : la recherche rendait None et l'outil répondait
    qu'il n'était dans aucun salon. Même patron que `_overlay_narrator`, qui
    cherche des deux côtés depuis toujours.
    """
    service = MagicMock()
    service.is_connected = True
    service.speak = AsyncMock(return_value="dit")

    # Chemin DISCORD : le service est posé directement sur le bot.
    cote_discord = _bot(owner="42")
    cote_discord.voice_service = service
    cote_discord.discord_bot = None
    rendu = await run_say_in_voice_tool(
        cote_discord, {"text": "coucou"}, roles=["admin"], maison=True)
    assert "à voix haute" in rendu, (
        "depuis Discord, Wally se croit hors du salon alors qu'il y est"
    )

    # Chemin TWITCH : le service est derrière la référence croisée.
    cote_twitch = _bot(owner="42")
    cote_twitch.voice_service = None
    cote_twitch.discord_bot = SimpleNamespace(voice_service=service)
    rendu = await run_say_in_voice_tool(
        cote_twitch, {"text": "coucou"}, roles=["moderator"], maison=True)
    assert "à voix haute" in rendu


@pytest.mark.asyncio
async def test_hors_salon_le_refus_reste():
    """La garde doit continuer de mordre quand il n'est VRAIMENT nulle part."""
    bot = _bot(owner="42")
    bot.voice_service = None
    bot.discord_bot = None
    rendu = await run_say_in_voice_tool(
        bot, {"text": "coucou"}, roles=["admin"], maison=True)
    assert "Impossible" in rendu
