"""Une image postée doit laisser une trace de CE QU'ELLE MONTRE, pas seulement de qui l'a envoyée.

La description passait par `_post_process`, qui ne tourne qu'après une réponse
de Wally. Mesuré le 2026-08-26 : 23 faits « X a envoyé une image : … » en base
pour 230 messages avec image dans les journaux. D'une œuvre postée dans un salon
où il n'a rien à dire, il ne gardait que « Untel a envoyé une image » — de quoi
remercier la bonne personne, jamais de quoi dire ce qu'elle a fait.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.handlers import _memoriser_image


def make_bot(description="Un dessin de chat au feutre noir", disponible=True):
    bot = MagicMock()
    bot.vision.available = disponible
    bot.vision.analyze = AsyncMock(return_value=description)
    bot.memory.add = AsyncMock()
    return bot


async def test_le_fait_dit_qui_a_envoye_et_ce_qu_on_y_voit():
    bot = make_bot()

    assert await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"],
    )

    bot.memory.add.assert_awaited_once()
    args, kwargs = bot.memory.add.call_args
    assert args[0] == "discord"
    assert args[1] == "123"                       # id BRUT, jamais préfixé
    assert args[2] == "Rhao a envoyé une image : Un dessin de chat au feutre noir"
    assert kwargs["username"] == "Rhao"


async def test_une_analyse_deja_calculee_n_en_redemande_pas_une():
    """Sur le chemin d'une réponse, l'analyse existe déjà : la réutiliser ne
    doit coûter aucun appel de plus."""
    bot = make_bot()

    await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"], analysis="Une capture de stats Apex",
    )

    bot.vision.analyze.assert_not_awaited()
    assert "Une capture de stats Apex" in bot.memory.add.call_args.args[2]


async def test_une_description_bavarde_est_tronquee():
    bot = make_bot("mot " * 200)

    await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"],
    )

    contenu = bot.memory.add.call_args.args[2]
    assert contenu.endswith("…")
    assert len(contenu) < 300


async def test_sans_vision_rien_n_est_invente():
    """DeepSeek est aveugle : sans VisionService, mieux vaut aucun fait qu'un
    fait imaginé."""
    bot = make_bot(disponible=False)

    assert not await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"],
    )
    bot.memory.add.assert_not_awaited()


async def test_une_vision_en_panne_ne_fait_pas_tomber_le_message():
    bot = make_bot()
    bot.vision.analyze = AsyncMock(side_effect=RuntimeError("502 upstream"))

    assert not await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"],
    )
    bot.memory.add.assert_not_awaited()


async def test_une_analyse_vide_ne_produit_pas_un_fait_creux():
    bot = make_bot("   ")

    assert not await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao",
        image_urls=["http://img/1.png"],
    )
    bot.memory.add.assert_not_awaited()


async def test_un_message_sans_image_ne_coute_aucun_appel():
    bot = make_bot()

    assert not await _memoriser_image(
        bot, platform="discord", user_id="123", display_name="Rhao", image_urls=[],
    )
    bot.vision.analyze.assert_not_awaited()


# --- de bout en bout : le chemin SILENCIEUX ---------------------------------


def make_bot_discord():
    import discord

    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999
    bot.config.discord.allowed_channels = []
    bot.config.discord.channel_filter_mode = "none"
    bot.config.discord.per_guild_channel_whitelist = {}
    bot.config.discord.always_trigger_channels = []
    bot.config.discord.emoji_reaction_probability = 0.0
    bot.config.discord.spam_detection.enabled = False
    bot.config.bot.trigger_names = ["wally"]
    bot.config.bot.prelude_window_size = 5
    bot.config.bot.spontaneous_cooldown_seconds = 99999
    bot.config.bot.spontaneous_probability = 0.0
    bot.emotion.get_state = MagicMock(return_value={"curiosity": 0.0, "anger": 0.0})
    bot.memory.get_prelude = MagicMock(return_value=[])
    bot.memory.append_prelude = MagicMock()
    bot.memory.add = AsyncMock()
    bot.vision.available = True
    bot.vision.analyze = AsyncMock(return_value="Un fan-art de Wally en pixel art")
    bot.db.is_muted = AsyncMock(return_value=False)
    bot.db.is_chat_user_banned = AsyncMock(return_value=False)
    bot.fact_extractor = MagicMock()
    bot.cognitive_loop = None
    bot.response_gate = None
    return bot


def make_message_avec_image(contenu=""):
    import discord

    piece = MagicMock()
    piece.content_type = "image/png"
    piece.url = "https://cdn.discordapp.com/attachments/1/2/oeuvre.png"

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 123
    message.author.display_name = "Rhao"
    message.author.name = "rhao"
    message.content = contenu
    message.attachments = [piece]
    message.embeds = []
    message.mentions = []
    message.reference = None
    message.stickers = []
    message.id = 4242
    message.channel.id = 999
    message.channel.name = "artworks"
    message.channel.__class__ = discord.TextChannel
    message.channel.typing = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
    )
    message.guild.id = 456
    message.guild.name = "Le Purgatoire"
    message.add_reaction = AsyncMock()
    return message


async def test_une_oeuvre_postee_sans_interpeller_wally_est_quand_meme_vue():
    """Le cas #artworks : personne ne lui parle, il regarde quand même."""
    from bot.discord.handlers import handle_message

    bot = make_bot_discord()
    message = make_message_avec_image("regardez ce que j'ai fait")

    await handle_message(bot, message)
    for _ in range(6):
        await asyncio.sleep(0)

    bot.memory.add.assert_awaited()
    contenu = bot.memory.add.call_args.args[2]
    assert contenu == "Rhao a envoyé une image : Un fan-art de Wally en pixel art"
