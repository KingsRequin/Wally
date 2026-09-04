"""Le tronc commun des fiches Discord en Components V2 (`bot/discord/fiches.py`)."""
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.discord.commands.mood import accent_dominant
from bot.discord.commands.status import StatusCog
from bot.discord.fiches import (
    ACCENT_ALERTE,
    ACCENTS_EMOTION,
    fiche,
    url_avatar,
)


def _types(vue: discord.ui.LayoutView) -> list[str]:
    return [type(i).__name__ for i in vue.walk_children()]


def _textes(vue: discord.ui.LayoutView) -> list[str]:
    return [i.content for i in vue.walk_children()
            if isinstance(i, discord.ui.TextDisplay)]


def test_un_bloc_vide_ne_laisse_pas_de_trait_sur_du_vide():
    """Un rapport dont une section est absente ne doit pas rendre un séparateur
    suivi de rien — c'est ce que ferait une jointure naïve."""
    vue = fiche("T", ["premier", "", None or "", "second"])
    assert _types(vue).count("Separator") == 2
    assert _textes(vue) == ["## T", "premier", "second"]


def test_la_vignette_met_le_titre_en_section():
    avec = fiche("T", ["corps"], vignette="https://exemple/av.png")
    assert "Section" in _types(avec) and "Thumbnail" in _types(avec)
    sans = fiche("T", ["corps"])
    assert "Section" not in _types(sans)


def test_un_avatar_illisible_ne_part_pas_a_l_api():
    """Un `Thumbnail` construit sur autre chose qu'une chaîne revient en 400 :
    le garde est ce qui permet d'appeler `fiche()` sans savoir si l'objet est
    complet (un bot pas encore connecté n'a pas de `user`)."""
    assert url_avatar(MagicMock()) is None
    assert url_avatar(None) is None
    membre = MagicMock()
    membre.display_avatar.url = "https://exemple/av.png"
    assert url_avatar(membre) == "https://exemple/av.png"


def test_une_galerie_porte_plusieurs_images():
    """Ce qu'un embed ne savait pas faire : une seule fiche pour dix images."""
    vue = fiche("T", [], medias=[f"attachment://m{i}.png" for i in range(3)])
    galerie = next(i for i in vue.walk_children()
                   if isinstance(i, discord.ui.MediaGallery))
    assert len(galerie.items) == 3


# ── l'accent de /mood ─────────────────────────────────────────────────────────

def test_l_accent_suit_l_emotion_dominante():
    assert accent_dominant({"joy": 0.8, "anger": 0.1}) == ACCENTS_EMOTION["joy"]
    assert accent_dominant({"anger": 0.62, "joy": 0.6}) == ACCENTS_EMOTION["anger"]


def test_sous_le_seuil_aucune_emotion_ne_parle_pour_les_autres():
    """0.4 est le seuil des dominantes du projet : en dessous, colorer la fiche
    en rouge parce que la colère est à 0.09 dirait le contraire du vrai."""
    assert accent_dominant({"anger": 0.09, "joy": 0.05}) == ACCENT_ALERTE
    assert accent_dominant({}) == ACCENT_ALERTE


# ── /status ───────────────────────────────────────────────────────────────────

async def _fiche_de_status(bot) -> discord.ui.LayoutView:
    cog = StatusCog(bot)
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    await cog.status.callback(cog, interaction)
    return interaction.followup.send.call_args.kwargs["view"]


def _bot_status(*, voix: bool):
    bot = MagicMock()
    bot._start_time = None
    bot.config.llm.primary.provider = "deepseek"
    bot.config.llm.primary.model = "deepseek-v4"
    bot.config.voice.enabled = voix
    bot.emotion.get_dominant = MagicMock(return_value=["joy"])
    bot.image_client.get_daily_cost = AsyncMock(return_value=0.12)
    bot.image_client.get_monthly_cost = AsyncMock(return_value=3.4)
    bot.voice_service.quota.snapshot = MagicMock(return_value={
        "stt_remaining_seconds": 7200, "tts_remaining_chars": 250_000})
    return bot


async def test_le_quota_vocal_ne_s_affiche_que_si_la_voix_est_active():
    assert any("Vocal restant" in t for t in _textes(await _fiche_de_status(_bot_status(voix=True))))
    assert not any("Vocal restant" in t for t in _textes(await _fiche_de_status(_bot_status(voix=False))))


async def test_un_quota_illisible_n_efface_pas_le_reste_de_la_fiche():
    """C'est justement l'information qu'on veut voir AVANT que la voix
    s'arrête : la perdre ne doit pas emporter le statut avec elle."""
    bot = _bot_status(voix=True)
    bot.voice_service.quota.snapshot = MagicMock(side_effect=RuntimeError("azure muet"))
    textes = _textes(await _fiche_de_status(bot))
    assert any("deepseek/deepseek-v4" in t for t in textes)
    assert not any("Vocal restant" in t for t in textes)
