"""La commande `!clip` du chat — `!clip 50`, `!clip 1m`, `!clip 30 titre`.

Demandée par l'owner le 2026-09-01 en plus de l'outil `create_clip` : elle ne
coûte aucun appel LLM et part tout de suite. Ce qui est vérifié ici, c'est
surtout ce qu'elle PARTAGE avec l'outil — le cooldown de chaîne — et ce qu'elle
ne partage pas : les phrases rendues au modèle n'ont rien à faire dans le chat.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.tools.clip_tool as clip_tool
from bot.tools.clip_tool import run_clip_tool
from bot.twitch.commands.clip import handle_clip_command, parse_args


@pytest.fixture(autouse=True)
def _cooldown_neuf():
    clip_tool._dernier_clip_a = 0.0
    yield
    clip_tool._dernier_clip_a = 0.0


def _bot(clip=None):
    b = MagicMock()
    b.twitch_api = MagicMock()
    b.twitch_api.CLIP_DUREE_MAX_S = 60
    b.twitch_api.create_clip = AsyncMock(return_value=clip)
    b.twitch_api.send_message = AsyncMock(return_value=True)
    return b


def _dit(b) -> str:
    return b.twitch_api.send_message.await_args.args[0]


@pytest.mark.parametrize("args, attendu", [
    ("", (0, "")),
    ("50", (50, "")),
    ("50s", (50, "")),
    ("1m", (60, "")),
    ("2 min", (120, "")),
    ("30 kill au wingman", (30, "kill au wingman")),
    ("kill au wingman", (0, "kill au wingman")),
    # La durée se lit EN TÊTE seulement : sinon ce titre-là perdrait son
    # « 1 seconde » au profit d'une durée que personne n'a demandée.
    ("2 kills en 1 seconde", (2, "kills en 1 seconde")),
])
def test_la_duree_et_le_titre_se_lisent_dans_la_commande(args, attendu):
    assert parse_args(args) == attendu


async def test_la_commande_clippe_et_rend_le_lien():
    b = _bot({"url": "https://clips.twitch.tv/Abc", "title": "kill"})
    await handle_clip_command(b, "viewer", "45 kill au wingman")
    b.twitch_api.create_clip.assert_awaited_once_with("kill au wingman", 45)
    assert "https://clips.twitch.tv/Abc" in _dit(b)
    assert _dit(b).startswith("@viewer ")


async def test_une_minute_demandee_est_une_minute_envoyee():
    b = _bot({"url": "https://c/1"})
    await handle_clip_command(b, "viewer", "1m")
    b.twitch_api.create_clip.assert_awaited_once_with("", 60)


async def test_la_commande_PARTAGE_le_cooldown_de_l_outil():
    """Deux compteurs séparés donneraient deux clips du même moment."""
    b = _bot({"url": "https://c/1"})
    assert json.loads(await run_clip_tool(b, {}))["status"] == "ok"

    await handle_clip_command(b, "viewer", "")
    # Un seul appel à l'API : la commande a vu le cooldown posé par l'outil.
    assert b.twitch_api.create_clip.await_count == 1
    assert "Encore" in _dit(b)


async def test_le_chat_ne_recoit_PAS_les_consignes_ecrites_pour_le_modele():
    """« Ne donne AUCUNE URL », « Dis-le » : ces phrases s'adressent au LLM."""
    b = _bot(None)
    await handle_clip_command(b, "viewer", "")
    dit = _dit(b)
    assert "Dis-le" not in dit
    assert "AUCUNE URL" not in dit
    assert "live" in dit.lower()


async def test_une_demande_trop_longue_dit_ce_qu_elle_a_vraiment_eu():
    b = _bot({"url": "https://c/1"})
    await handle_clip_command(b, "viewer", "3m")
    dit = _dit(b)
    assert "https://c/1" in dit
    assert "60" in dit and "180" in dit


async def test_sans_api_twitch_la_commande_se_tait_au_lieu_de_lever():
    b = MagicMock()
    b.twitch_api = None
    b._twitch_bot = None
    await handle_clip_command(b, "viewer", "")   # ne lève pas


async def test_le_clip_est_refuse_depuis_une_chaine_invitee():
    """Le token streamer ne vaut que chez Azraël : `!clip` y clipperait SON live."""
    from bot.twitch.commands import dispatch_command

    b = _bot({"url": "https://c/1"})
    b.config.overlay_image.enabled = False
    b._channel_ids = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("bot.twitch.handlers.est_chaine_home",
                   lambda bot, chan: chan == "azrael_ttv")
        traite = await dispatch_command(b, MagicMock(), "!clip 30", "viewer", "autre_chaine")
    assert traite is False
    b.twitch_api.create_clip.assert_not_awaited()


async def test_le_clip_passe_par_le_dispatch_sur_la_chaine_maison():
    from bot.twitch.commands import dispatch_command

    b = _bot({"url": "https://c/1"})
    b.config.overlay_image.enabled = False
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("bot.twitch.handlers.est_chaine_home",
                   lambda bot, chan: chan == "azrael_ttv")
        traite = await dispatch_command(b, MagicMock(), "!clip 30", "viewer", "azrael_ttv")
    assert traite is True
    b.twitch_api.create_clip.assert_awaited_once_with("", 30)
