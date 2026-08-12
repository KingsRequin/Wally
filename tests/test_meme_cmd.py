# tests/test_meme_cmd.py
"""La commande contextuelle qui range un meme."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.discord.commands.meme_cmd import MemeCog, image_du_message


def _piece_jointe(url="https://cdn.discordapp.com/a/chat.png", content_type="image/png"):
    a = MagicMock()
    a.url = url
    a.content_type = content_type
    return a


def _message(attachments=(), embeds=()):
    m = MagicMock()
    m.attachments = list(attachments)
    m.embeds = list(embeds)
    return m


def test_la_piece_jointe_est_prioritaire():
    embed = MagicMock()
    embed.image.url = "https://tenor.com/x.gif"
    assert image_du_message(_message([_piece_jointe()], [embed])) == (
        "https://cdn.discordapp.com/a/chat.png", ".png",
    )


def test_l_image_d_un_embed_sert_de_repli():
    embed = MagicMock()
    embed.image.url = "https://media.tenor.com/abc.gif"
    embed.thumbnail.url = None
    assert image_du_message(_message([], [embed])) == (
        "https://media.tenor.com/abc.gif", ".gif",
    )


def test_un_message_sans_image_ne_donne_rien():
    assert image_du_message(_message()) is None


def test_une_piece_jointe_non_image_est_ignoree():
    doc = _piece_jointe(url="https://cdn.discordapp.com/a/notes.pdf",
                        content_type="application/pdf")
    assert image_du_message(_message([doc])) is None


def _bot(tmp_path):
    bot = MagicMock()
    bot.tree.add_command = MagicMock()
    bot.vision.available = True
    bot.vision.analyze = AsyncMock(return_value="Chat à lunettes. Texte : « QUAND TU ATTENDS ».")
    return bot


def _interaction():
    i = MagicMock()
    i.user.id = 42
    i.user.display_name = "Testeur"
    i.response.defer = AsyncMock()
    i.response.send_message = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.followup.send = AsyncMock()
    i.channel.send = AsyncMock()
    return i


@pytest.mark.asyncio
async def test_l_apercu_propose_la_description_sans_rien_ecrire(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(
        "bot.discord.commands.meme_cmd.telecharger",
        AsyncMock(return_value=b"\x89PNG\r\n\x1a\n"),
    )
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message([_piece_jointe()]))

    envoi = interaction.followup.send.call_args
    assert "Chat à lunettes" in envoi.kwargs["content"]
    assert list(tmp_path.iterdir()) == []  # rien n'est écrit avant validation


@pytest.mark.asyncio
async def test_un_message_sans_image_est_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message())

    assert "image" in interaction.followup.send.call_args.kwargs["content"].lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_un_doublon_nomme_le_fichier_deja_range(tmp_path, monkeypatch):
    from PIL import Image

    Image.new("RGB", (60, 60), (9, 9, 9)).save(tmp_path / "meme1.webp", "WEBP")
    octets = (tmp_path / "meme1.webp").read_bytes()
    monkeypatch.setattr("bot.discord.commands.meme_cmd.DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(
        "bot.discord.commands.meme_cmd.telecharger", AsyncMock(return_value=octets)
    )
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message([_piece_jointe(url="https://cdn/x.webp",
                                                          content_type="image/webp")]))

    assert "meme1.webp" in interaction.followup.send.call_args.kwargs["content"]
    assert not (tmp_path / "meme2.webp").exists()
