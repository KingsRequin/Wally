# tests/test_meme_masse.py
"""L'import de memes en masse : ratisser un salon, ou ranger au fil de l'eau.

Ce que ces tests tiennent, et que le chemin unitaire ne pouvait pas tenir : la
description est PAYANTE et lente, donc elle ne doit jamais toucher un doublon ;
et une limite annoncée est une limite qui arrête vraiment.
"""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from PIL import Image

from bot.core import meme_import
from bot.discord.commands import meme_masse


def _png(couleur=(0, 120, 255)) -> bytes:
    tampon = io.BytesIO()
    Image.new("RGB", (64, 64), couleur).save(tampon, "PNG")
    return tampon.getvalue()


def _png_de(url: str) -> bytes:
    """Une image DIFFÉRENTE par URL — sinon la dédup les confond, à raison."""
    n = abs(hash(url))
    return _png((n % 251, (n // 251) % 251, (n // 63001) % 251))


def _piece_jointe(url):
    a = MagicMock()
    a.url = url
    a.content_type = "image/png"
    return a


def _message(*urls, bot=False):
    m = MagicMock()
    m.channel = MagicMock(spec=discord.TextChannel)
    m.attachments = [_piece_jointe(u) for u in urls]
    m.embeds = []
    m.author.bot = bot
    m.author.id = 7 if bot else 42
    return m


def _salon(messages):
    # `spec=` n'est pas de la coquetterie : la commande refuse désormais ce qui
    # n'est pas un salon de serveur, et un mock sans spec passait pour un DM.
    salon = MagicMock(spec=discord.TextChannel)

    async def _history(**_kwargs):
        for m in messages:
            yield m

    salon.history = _history
    salon.mention = "#memes"
    return salon


# ── La fenêtre temporelle ─────────────────────────────────────────────────────


def test_la_barre_rend_le_pourcentage_et_les_pleins():
    assert meme_masse.barre(0, 10) == "`" + "░" * 20 + "` 0 %"
    assert meme_masse.barre(5, 10) == "`" + "█" * 10 + "░" * 10 + "` 50 %"
    assert meme_masse.barre(10, 10) == "`" + "█" * 20 + "` 100 %"


def test_un_salon_sans_image_ne_divise_pas_par_zero():
    """Un salon vide n'a rien à se reprocher : la barre ne doit pas lever."""
    assert meme_masse.barre(0, 0).endswith("0 %")


def test_la_progression_dit_sur_combien_et_pas_seulement_combien():
    bilan = meme_import.Bilan(ranges=["meme1.webp", "meme2.webp"], doublons=["meme9.webp"])
    salon = MagicMock(spec=discord.TextChannel)
    salon.mention = "#memes"

    texte = meme_masse.texte_progression(bilan, 10, salon)

    assert "**10 médias trouvés** dans #memes" in texte
    assert ", 3/10" in texte
    assert "30 %" in texte
    assert "✅ 2 rangés · 🔁 1 doublon" in texte


def test_avant_le_premier_rangement_la_ligne_de_comptes_se_tait():
    """« ✅ 0 rangé » n'apprend rien : seule la barre a quelque chose à dire."""
    salon = MagicMock(spec=discord.TextChannel)
    salon.mention = "#memes"

    texte = meme_masse.texte_progression(meme_import.Bilan(), 10, salon)

    assert "0/10" in texte
    assert "✅" not in texte


def test_un_salon_sans_media_le_dit_au_lieu_d_une_barre_a_zero():
    """Une barre à 0/0 laisse croire à un travail en cours qui n'existe pas."""
    salon = MagicMock(spec=discord.TextChannel)
    salon.mention = "#memes"

    assert meme_masse.texte_progression(meme_import.Bilan(), 0, salon) == (
        "Aucun média à ranger dans #memes."
    )


def test_la_periode_sans_borne_dit_tout_l_historique():
    fin = datetime(2026, 8, 20, 20, 30, tzinfo=timezone.utc)
    assert meme_masse.periode_lisible(None, fin) == (
        "tout l'historique, jusqu'au 20/08/2026 à 22h30"
    )


def test_la_periode_bornee_est_rendue_en_heure_de_paris():
    """L'hôte est en UTC : rendre la borne en naïf décalerait le rapport de 2 h."""
    debut = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    fin = datetime(2026, 8, 20, 20, 30, tzinfo=timezone.utc)
    assert meme_masse.periode_lisible(debut, fin) == (
        "du 13/08/2026 à 08h00 au 20/08/2026 à 22h30"
    )


def test_une_fenetre_en_jours_remonte_dans_le_passe():
    apres = meme_masse.fenetre("7j")
    assert apres is not None
    ecart = datetime.now(timezone.utc) - apres
    assert timedelta(days=6, hours=23) < ecart < timedelta(days=7, minutes=1)


def test_tout_ne_borne_rien():
    assert meme_masse.fenetre("tout") is None


def test_une_date_est_lue_dans_le_fuseau_de_paris():
    """CT100 tourne en UTC, l'application raisonne en Europe/Paris : lire une
    date en naïf ferait commencer « le 1er août » à 2 h du matin."""
    apres = meme_masse.fenetre("2026-08-01")
    assert apres is not None
    assert apres.utcoffset() == timedelta(hours=2)  # CEST
    assert (apres.year, apres.month, apres.day, apres.hour) == (2026, 8, 1, 0)


@pytest.mark.parametrize("mauvais", ["", "la semaine dernière", "7", "j7", "2026-13-01"])
def test_une_fenetre_illisible_est_refusee_par_son_nom(mauvais):
    with pytest.raises(ValueError):
        meme_masse.fenetre(mauvais)


# ── Le ratissage ──────────────────────────────────────────────────────────────


@pytest.fixture
def decrire():
    return AsyncMock(return_value="un chat qui boude")


async def test_les_images_du_salon_sont_rangees(tmp_path, monkeypatch, decrire):
    images = {"https://cdn/a.png": _png((1, 2, 3)), "https://cdn/b.png": _png((250, 2, 3))}
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=images.get))

    bilan = await meme_masse.importer_salon(
        _salon([_message("https://cdn/a.png"), _message("https://cdn/b.png")]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
    )

    assert bilan.ranges == ["meme1.webp", "meme2.webp"]
    assert (tmp_path / "meme1.webp.txt").read_text(encoding="utf-8") == "un chat qui boude"


async def test_un_meme_deja_range_a_la_main_n_est_pas_decrit(tmp_path, monkeypatch, decrire):
    """Le nerf de l'affaire : la vision coûte un appel et quelques secondes par
    image. Sur un salon dont la moitié est déjà en banque, décrire avant de
    dédoublonner double la facture ET la durée."""
    deja = _png((5, 5, 5))
    meme_import.importer(deja, ".png", "rangé à la main", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect={
        "https://cdn/vieux.png": deja, "https://cdn/neuf.png": _png((7, 7, 7)),
    }.get))

    bilan = await meme_masse.importer_salon(
        _salon([_message("https://cdn/vieux.png", "https://cdn/neuf.png")]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
    )

    assert decrire.await_count == 1
    assert bilan.doublons == ["meme1.webp"]
    assert bilan.ranges == ["meme2.webp"]


async def test_la_limite_arrete_vraiment(tmp_path, monkeypatch, decrire):
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message(f"https://cdn/{i}0000.png") for i in range(9)])

    bilan = await meme_masse.importer_salon(
        salon, apres=None, limite=3, dossier=tmp_path, decrire=decrire,
    )

    assert len(bilan.ranges) == 3
    assert decrire.await_count == 3  # on ne décrit pas ce qu'on ne rangera pas
    assert bilan.interrompu


async def test_un_telechargement_rate_ne_coupe_pas_le_lot(tmp_path, monkeypatch, decrire):
    async def _tele(url):
        if "casse" in url:
            raise ValueError("403 du CDN")
        return _png((3, 3, 3))

    monkeypatch.setattr(meme_masse, "telecharger", _tele)

    bilan = await meme_masse.importer_salon(
        _salon([_message("https://cdn/casse.png"), _message("https://cdn/bon.png")]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
    )

    assert bilan.ranges == ["meme1.webp"]
    assert "403 du CDN" in " ".join(bilan.refus)


async def test_les_memes_annonces_par_wally_ne_sont_pas_reranges(tmp_path, monkeypatch, decrire):
    """Wally annonce chaque rangement dans le salon, pièce jointe comprise :
    ratisser sans l'écarter ferait repasser toute la banque par la vision."""
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(return_value=_png()))
    salon = _salon([_message("https://cdn/annonce.png", bot=True)])

    bilan = await meme_masse.importer_salon(
        salon, apres=None, limite=100, dossier=tmp_path, decrire=decrire,
        moi=7,
    )

    assert bilan.ranges == []
    assert decrire.await_count == 0


async def test_un_message_a_plusieurs_medias_les_range_tous(tmp_path, monkeypatch, decrire):
    """Un message porte jusqu'à dix pièces jointes — n'en prendre qu'une en
    laisserait neuf dans le salon sans que rien ne le signale."""
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/a.png", "https://cdn/b.png", "https://cdn/c.png")])

    bilan = await meme_masse.importer_salon(
        salon, apres=None, limite=100, dossier=tmp_path, decrire=decrire, moi=7,
    )

    assert len(bilan.ranges) == 3


async def test_wally_est_ecarte_meme_quand_il_poste_plusieurs_medias(tmp_path, monkeypatch,
                                                                     decrire):
    """La garde porte sur le MESSAGE, pas sur sa première pièce jointe."""
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/x.png", "https://cdn/y.png", bot=True)])

    bilan = await meme_masse.importer_salon(
        salon, apres=None, limite=100, dossier=tmp_path, decrire=decrire, moi=7,
    )

    assert bilan.ranges == []
    assert decrire.await_count == 0


async def test_le_rapport_nomme_ce_qui_a_ete_ecarte(tmp_path, monkeypatch, decrire):
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(return_value=_png()))
    bilan = await meme_masse.importer_salon(
        _salon([_message("https://cdn/a.png"), _message("https://cdn/a.png")]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
    )

    texte = bilan.texte()
    assert "1 rangé" in texte
    assert "1 doublon" in texte
    assert "meme1.webp" in texte


async def test_la_progression_est_rapportee_en_cours_de_route(tmp_path, monkeypatch, decrire):
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    vus = []

    async def _noter(bilan, total):
        vus.append((len(bilan.ranges), total))

    await meme_masse.importer_salon(
        _salon([_message(f"https://cdn/{i}0000.png") for i in range(6)]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
        progression=_noter,
    )

    assert vus  # l'appelant a de quoi éditer son message d'attente
    assert vus[-1] == (6, 6)


async def test_le_total_est_annonce_avant_le_premier_paquet(tmp_path, monkeypatch, decrire):
    """Rapatrier et décrire quatre images prend une dizaine de secondes : sans
    cette annonce, l'admin n'a RIEN sous les yeux pendant ce temps-là."""
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    vus = []

    async def _noter(bilan, total):
        vus.append((len(bilan.ranges), total))

    await meme_masse.importer_salon(
        _salon([_message(f"https://cdn/{i}0000.png") for i in range(6)]),
        apres=None, limite=100, dossier=tmp_path, decrire=decrire,
        progression=_noter,
    )

    assert vus[0] == (0, 6)  # le dénominateur AVANT le premier rangement


# ── La commande, et le dépôt au fil de l'eau ──────────────────────────────────


def _bot(salon_depot=None):
    bot = MagicMock()
    bot.user.id = 7
    bot.vision.available = True
    bot.vision.analyze = AsyncMock(return_value="un chat qui boude")
    bot.config.discord.meme_channel_id = salon_depot
    return bot


def _interaction(salon=None):
    i = MagicMock()
    i.user.id = 42
    i.user.display_name = "Testeur"
    i.channel = salon or _salon([])
    i.guild.me = MagicMock()
    i.response.defer = AsyncMock()
    i.response.send_message = AsyncMock()
    i.followup.send = AsyncMock()
    i.edit_original_response = AsyncMock()
    return i


async def test_une_fenetre_illisible_est_dite_avant_de_ratisser(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    interaction = _interaction()

    await meme_masse.MemeMasseCog(_bot()).importer.callback(
        meme_masse.MemeMasseCog(_bot()), interaction, depuis="la semaine dernière"
    )

    assert "7j" in interaction.response.send_message.call_args.kwargs["content"]
    assert interaction.response.defer.await_count == 0  # rien n'a commencé


async def test_la_commande_rend_le_rapport_du_ratissage(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/a.png"), _message("https://cdn/b.png")])
    salon.permissions_for = MagicMock(return_value=MagicMock(read_message_history=True))
    interaction = _interaction(salon)
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, depuis="tout")

    embed = salon.send.call_args.kwargs["embed"]
    assert "`meme1.webp` `meme2.webp`" in embed.description
    assert sorted(p.name for p in tmp_path.glob("*.webp")) == ["meme1.webp", "meme2.webp"]


async def test_le_rapport_final_est_public_et_porte_les_comptes(tmp_path, monkeypatch):
    """Éphémère, le rapport disparaissait avec l'onglet : plus personne ne
    pouvait dire d'où sortaient les nouveaux memes de l'overlay."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/a.png"), _message("https://cdn/a.png")])
    salon.permissions_for = MagicMock(return_value=MagicMock(read_message_history=True))
    interaction = _interaction(salon)
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, depuis="tout")

    # Le rapport part par le salon : un followup d'interaction déférée en
    # éphémère peut hériter du flag et n'être vu que de l'admin.
    assert interaction.followup.send.await_count == 0
    champs = {c.name: c.value for c in salon.send.call_args.kwargs["embed"].fields}
    assert champs["Rangés"] == "1"
    assert champs["Doublons"] == "1"
    assert "tout l'historique" in champs["Période"]


async def test_le_message_d_attente_porte_la_barre_et_le_total(tmp_path, monkeypatch):
    """Le compte rendu d'attente disait « 2 rangés » sans jamais dire sur combien."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/a.png"), _message("https://cdn/b.png")])
    salon.permissions_for = MagicMock(return_value=MagicMock(read_message_history=True))
    interaction = _interaction(salon)
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, depuis="tout")

    attente = interaction.edit_original_response.call_args_list[0].kwargs["content"]
    assert "**2 médias trouvés**" in attente
    assert "0/2" in attente


async def test_la_progression_ephemere_se_clot(tmp_path, monkeypatch):
    """Sans ça, l'admin garde « Rangement en cours… » sous les yeux pour toujours."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    salon = _salon([_message("https://cdn/a.png")])
    salon.permissions_for = MagicMock(return_value=MagicMock(read_message_history=True))
    interaction = _interaction(salon)
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, depuis="tout")

    assert interaction.edit_original_response.call_args.kwargs["content"] == "Ratissage terminé."


async def test_un_salon_illisible_le_dit_au_lieu_d_echouer(tmp_path, monkeypatch):
    """Sans « Voir l'historique », `history()` lève une Forbidden opaque."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    salon = _salon([])
    salon.permissions_for = MagicMock(return_value=MagicMock(read_message_history=False))
    interaction = _interaction(salon)
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, salon=salon)

    assert "historique" in interaction.followup.send.call_args.kwargs["content"]


async def test_la_commande_est_reservee_a_la_gestion_du_serveur():
    cog = meme_masse.MemeMasseCog(_bot())
    assert cog.importer.default_permissions.manage_guild


# ── Boîte aux lettres ─────────────────────────────────────────────────────────


async def test_une_image_postee_dans_le_salon_de_depot_est_rangee(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    cog = meme_masse.MemeMasseCog(_bot(salon_depot=555))
    message = _message("https://cdn/a.png")
    message.channel.id = 555
    message.add_reaction = AsyncMock()

    await cog.au_fil_de_l_eau(message)

    assert (tmp_path / "meme1.webp").exists()
    assert message.add_reaction.await_args.args == ("✅",)


async def test_un_doublon_depose_est_signale_sans_etre_range(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    octets = _png_de("https://cdn/a.png")
    meme_import.importer(octets, ".png", "déjà là", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(return_value=octets))
    cog = meme_masse.MemeMasseCog(_bot(salon_depot=555))
    message = _message("https://cdn/a.png")
    message.channel.id = 555
    message.add_reaction = AsyncMock()

    await cog.au_fil_de_l_eau(message)

    assert message.add_reaction.await_args.args == ("🔁",)
    assert not (tmp_path / "meme2.webp").exists()


async def test_un_salon_ordinaire_n_est_pas_une_boite_aux_lettres(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    cog = meme_masse.MemeMasseCog(_bot(salon_depot=555))
    message = _message("https://cdn/a.png")
    message.channel.id = 999
    message.add_reaction = AsyncMock()

    await cog.au_fil_de_l_eau(message)

    assert list(tmp_path.iterdir()) == []
    assert message.add_reaction.await_count == 0


async def test_wally_ne_range_pas_ses_propres_annonces(tmp_path, monkeypatch):
    """Il annonce chaque rangement dans le salon, pièce jointe comprise : sans
    cette garde, chaque meme rangé en déclencherait un autre."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_masse, "telecharger", AsyncMock(side_effect=_png_de))
    cog = meme_masse.MemeMasseCog(_bot(salon_depot=555))
    message = _message("https://cdn/a.png", bot=True)  # author.id == 7, comme le bot
    message.channel.id = 555
    message.add_reaction = AsyncMock()

    await cog.au_fil_de_l_eau(message)

    assert list(tmp_path.iterdir()) == []


async def test_le_depot_arme_se_dit_une_seule_fois_au_boot():
    """`on_ready` retombe à chaque reconnexion — l'annonce, elle, ne doit pas."""
    from loguru import logger

    bot = _bot(salon_depot=555)
    salon = MagicMock()
    salon.name = "depot-memes"  # `name=` est réservé par MagicMock
    bot.get_channel.return_value = salon
    cog = meme_masse.MemeMasseCog(bot)
    lignes: list[str] = []
    sink = logger.add(lambda m: lignes.append(str(m)), level="INFO")
    try:
        await cog.annoncer_le_depot()
        await cog.annoncer_le_depot()
    finally:
        logger.remove(sink)

    assert bot.get_channel.call_count == 1
    assert sum("armé" in l for l in lignes) == 1


async def test_un_salon_de_depot_introuvable_est_dit_fort():
    """Sans la commande, un id périmé dans le config ne se voit QUE dans les logs."""
    from loguru import logger

    bot = _bot(salon_depot=555)
    bot.get_channel.return_value = None
    cog = meme_masse.MemeMasseCog(bot)
    lignes: list[str] = []
    sink = logger.add(lambda m: lignes.append(str(m)), level="WARNING")
    try:
        await cog.annoncer_le_depot()
    finally:
        logger.remove(sink)

    assert any("INTROUVABLE" in l for l in lignes)


async def test_la_commande_refuse_le_message_prive(tmp_path, monkeypatch):
    """En DM il n'y a ni serveur ni permissions : `permissions_for` lèverait."""
    monkeypatch.setattr(meme_masse, "DOSSIER_MEMES", tmp_path)
    interaction = _interaction()
    interaction.guild = None
    cog = meme_masse.MemeMasseCog(_bot())

    await cog.importer.callback(cog, interaction, depuis="tout")

    assert "privé" in interaction.followup.send.call_args.kwargs["content"]
