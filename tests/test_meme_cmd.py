# tests/test_meme_cmd.py
"""La commande contextuelle qui range un meme."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.core import meme_import
from bot.discord.commands import meme_cmd
from bot.discord.commands.meme_cmd import (
    Entree,
    FormulaireDescription,
    MemeCog,
    VueRangement,
    cible_publique,
    image_du_message,
    telecharger,
)

_MP4 = b"\x00\x00\x00\x18ftypmp42"


def _png(couleur=(0, 120, 255)) -> bytes:
    """Une vraie image : `importer()` la convertit, donc elle doit être décodable."""
    import io

    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (120, 120), couleur).save(tampon, "PNG")
    return tampon.getvalue()


_PNG = _png()


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
    embed.thumbnail.url = None
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


def _interaction(user_id=42):
    i = MagicMock()
    i.user.id = user_id
    i.user.display_name = "Testeur"
    i.response.defer = AsyncMock()
    i.response.send_message = AsyncMock()
    i.response.send_modal = AsyncMock()
    i.response.edit_message = AsyncMock()
    i.followup.send = AsyncMock()
    i.channel.send = AsyncMock()
    return i


def _salon():
    s = MagicMock()
    s.send = AsyncMock()
    return s


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


class _Reponse:
    def __init__(self, status=200, headers=None, corps=b""):
        self.status = status
        self.headers = headers or {}
        self._corps = corps
        self.content = self

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def iter_chunked(self, _taille):
        yield self._corps

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _Session:
    def __init__(self, *reponses):
        self._reponses = list(reponses)
        self.demandes = []

    def get(self, url, allow_redirects=True):
        self.demandes.append((url, allow_redirects))
        return self._reponses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


# ── La garde SSRF ──────────────────────────────────────────────────────────────
# L'URL vient d'un embed, donc de l'extérieur. Sans garde, un webhook postant
# `http://192.168.1.185:5001/x.png` faisait rapatrier la réponse depuis le
# réseau du conteneur, l'écrire sur disque, et la REPUBLIER en pièce jointe dans
# le salon : un chemin d'exfiltration complet.


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://192.168.1.185:5001/x.png",     # LXC hôte
    "http://127.0.0.1:8080/gallery/x.png",  # le bot lui-même
    "http://[::1]:8080/x.png",
    "http://169.254.169.254/latest/meta-data/",  # métadonnées cloud
    "http://wally-qdrant:6333/collections/x.png",  # alias Docker interne
])
async def test_une_cible_interne_est_refusee(url):
    assert await cible_publique(url) != ""


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://ailleurs.fr/x.png"])
async def test_seuls_http_et_https_passent(url):
    assert "refusé" in await cible_publique(url)


@pytest.mark.asyncio
async def test_le_telechargement_refuse_une_cible_interne_sans_requete(monkeypatch):
    """Le refus doit tomber AVANT la requête, pas après."""
    session = _Session()
    monkeypatch.setattr(meme_cmd.aiohttp, "ClientSession", lambda **_: session)

    with pytest.raises(PermissionError):
        await telecharger("http://192.168.1.185:5001/x.png")
    assert session.demandes == []


def _brancher(monkeypatch, session, publique=True):
    monkeypatch.setattr(meme_cmd.aiohttp, "ClientSession", lambda **_: session)
    monkeypatch.setattr(
        meme_cmd, "cible_publique",
        AsyncMock(return_value="" if publique else "interne"),
    )


@pytest.mark.asyncio
async def test_une_redirection_vers_une_cible_interne_est_refusee(monkeypatch):
    """aiohttp suit les redirections par défaut : une cible publique qui renvoie
    un `Location:` interne suffirait à contourner la garde."""
    session = _Session(_Reponse(302, {"Location": "http://192.168.1.185:5001/x.png"}))
    monkeypatch.setattr(meme_cmd.aiohttp, "ClientSession", lambda **_: session)

    with pytest.raises(PermissionError):
        await telecharger("https://media.tenor.com/abc.gif")

    assert session.demandes == [("https://media.tenor.com/abc.gif", False)]


@pytest.mark.asyncio
async def test_une_redirection_publique_est_suivie(monkeypatch):
    session = _Session(
        _Reponse(301, {"Location": "/ailleurs.png"}),
        _Reponse(200, corps=b"des octets"),
    )
    _brancher(monkeypatch, session)

    assert await telecharger("https://cdn.exemple.fr/x.png") == b"des octets"
    assert [u for u, _ in session.demandes] == [
        "https://cdn.exemple.fr/x.png", "https://cdn.exemple.fr/ailleurs.png",
    ]


@pytest.mark.asyncio
async def test_un_fichier_trop_gros_coupe_le_flux(monkeypatch):
    _brancher(monkeypatch, _Session(_Reponse(200, corps=b"\x00" * 4096)))

    with pytest.raises(ValueError):
        await telecharger("https://cdn.exemple.fr/x.png", limite=1024)


# ── Le rangement de bout en bout ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ranger_ecrit_le_fichier_le_sidecar_et_annonce(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip qui tourne")], salon)

    await vue.ranger(_interaction())

    assert (tmp_path / "meme1.mp4").read_bytes() == _MP4
    assert (tmp_path / "meme1.mp4.txt").read_text(encoding="utf-8") == "un clip qui tourne"
    assert salon.send.await_count == 1
    embed = salon.send.call_args.kwargs["embed"]
    assert "meme1.mp4" in str(embed.to_dict())
    assert isinstance(salon.send.call_args.kwargs["file"], discord.File)
    assert vue.is_finished()


@pytest.mark.asyncio
async def test_l_annonce_montre_l_image_dans_l_embed(tmp_path, monkeypatch):
    """Une image s'affiche DANS l'embed, via la pièce jointe qui l'accompagne."""
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [Entree(_PNG, ".png", "un carré")], salon)

    await vue.ranger(_interaction())

    embed = salon.send.call_args.kwargs["embed"]
    nom = salon.send.call_args.kwargs["file"].filename
    assert embed.image.url == f"attachment://{nom}"
    assert "Testeur" in str(embed.to_dict())


@pytest.mark.asyncio
async def test_l_annonce_ne_pose_pas_de_video_en_image_d_embed(tmp_path, monkeypatch):
    """Un `.mp4` en `set_image` donne un cadre vide : la vidéo reste en pièce jointe.

    Discord n'affiche pas de vidéo dans un embed. L'y désigner ne casse rien
    côté API, mais rend un embed avec un emplacement d'image qui ne se remplit
    jamais — le meme paraît manquant alors qu'il est bien joint en dessous.
    """
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip")], salon)

    await vue.ranger(_interaction())

    assert salon.send.call_args.kwargs["embed"].image.url is None


@pytest.mark.asyncio
async def test_l_annonce_ne_publie_pas_la_description(tmp_path, monkeypatch):
    """La description est le contexte interne de Wally, jamais du texte à lire.

    Même règle que sur l'overlay, où la légende a été retirée pour cette raison.
    """
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [Entree(_PNG, ".png", "SECRET DE POLICHINELLE")], salon)

    await vue.ranger(_interaction())

    assert "SECRET DE POLICHINELLE" not in str(salon.send.call_args.kwargs["embed"].to_dict())


@pytest.mark.asyncio
async def test_une_annonce_impossible_ne_laisse_pas_croire_a_un_echec(tmp_path, monkeypatch):
    """Le seul appel réseau ordinaire du chemin d'écriture : « Joindre des
    fichiers » absente, salon en lecture seule, ou fichier au-dessus de la
    limite d'upload du serveur. Sans garde, l'exception partait dans
    `View.on_error` — donc dans le `logging` standard, hors des sinks du projet
    — et l'utilisateur restait sur un « Rangé » sans jamais voir l'annonce."""
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    salon.send = AsyncMock(side_effect=RuntimeError("Missing Permissions"))
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip")], salon)
    interaction = _interaction()

    await vue.ranger(interaction)

    assert (tmp_path / "meme1.mp4").is_file()      # le fichier EST rangé
    dit = interaction.followup.send.call_args.kwargs["content"]
    assert "meme1.mp4" in dit and "rangé" in dit and "annonce" in dit
    assert vue.is_finished()                        # stop() est bien atteint


@pytest.mark.asyncio
async def test_un_autre_utilisateur_ne_peut_pas_ranger(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip")], _salon())
    intrus = _interaction(user_id=99)

    assert await vue.interaction_check(intrus) is False
    assert "pas le tien" in intrus.response.send_message.call_args.args[0]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_annuler_n_ecrit_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip")], salon)
    interaction = _interaction()

    await vue.bouton_annuler.callback(interaction)

    assert list(tmp_path.iterdir()) == []
    assert salon.send.await_count == 0
    assert vue.is_finished()


@pytest.mark.asyncio
async def test_la_description_corrigee_est_celle_qui_est_ecrite(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "ce que la vision a cru voir")], _salon())
    formulaire = FormulaireDescription(vue)
    formulaire.description._value = "ce que l'owner a corrigé à la main"

    await formulaire.on_submit(_interaction())

    assert (tmp_path / "meme1.mp4.txt").read_text(encoding="utf-8") == (
        "ce que l'owner a corrigé à la main"
    )


def test_le_formulaire_supporte_une_longue_description():
    """`default` DOIT tenir dans `max_length` : discord.py ne le vérifie pas,
    c'est l'API qui rejette en 400 et `send_modal` lève. La vision tourne à 400
    tokens — largement de quoi dépasser la borne du champ."""
    from bot.core.memes import MAX_DESCRIPTION

    vue = VueRangement(42, [Entree(_MP4, ".mp4", "Un chat très mécontent. " * 40)], _salon())

    champ = FormulaireDescription(vue).description
    assert len(champ.default) <= champ.max_length == MAX_DESCRIPTION


@pytest.mark.asyncio
async def test_l_apercu_expire_en_grisant_ses_boutons(tmp_path):
    """Passé 120 s Discord ne route plus l'interaction : un bouton resté
    cliquable rend « Cette interaction a échoué », ce qui passe pour une panne."""
    vue = VueRangement(42, [Entree(_MP4, ".mp4", "un clip")], _salon())
    vue.message = MagicMock()
    vue.message.edit = AsyncMock()

    await vue.on_timeout()

    assert all(enfant.disabled for enfant in vue.children)
    assert vue.message.edit.await_count == 1


def test_la_commande_est_reservee_a_la_gestion_du_serveur(tmp_path):
    """Le dossier alimente un overlay diffusé en direct : un dépôt malvenu
    sortirait à l'antenne. Une ligne, et c'est le seul garde-fou."""
    cog = MemeCog(_bot(tmp_path))

    assert cog.menu.default_permissions == discord.Permissions(manage_guild=True)


# ── Ce que l'aperçu annonce ────────────────────────────────────────────────────


def test_un_format_non_admis_est_rendu_tel_quel_pas_efface():
    """Le rendre `None` était le mensonge d'origine déplacé : l'utilisateur
    lisait « ce message ne porte aucune image » devant une image bien visible.
    L'appelant doit recevoir de quoi nommer le format."""
    bmp = _piece_jointe(url="https://cdn.discordapp.com/a/vieux.bmp",
                        content_type="image/bmp")
    assert image_du_message(_message([bmp])) == (
        "https://cdn.discordapp.com/a/vieux.bmp", ".bmp",
    )


def test_un_format_admis_l_emporte_sur_un_format_qui_ne_l_est_pas():
    heic = _piece_jointe(url="https://cdn.discordapp.com/a/photo.heic",
                         content_type="image/heic")
    png = _piece_jointe(url="https://cdn.discordapp.com/a/chat.png")

    assert image_du_message(_message([heic, png])) == (
        "https://cdn.discordapp.com/a/chat.png", ".png",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("nom,mime", [("clip.mov", "video/quicktime"),
                                      ("vieux.bmp", "image/bmp"),
                                      ("photo.heic", "image/heic")])
async def test_un_format_non_admis_est_nomme_pas_nie(tmp_path, monkeypatch, nom, mime):
    """« Ce message ne porte aucune image » devant une vidéo iPhone envoie
    chercher un problème dans le message, alors qu'il est dans le format."""
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_cmd, "telecharger",
                        AsyncMock(side_effect=AssertionError("rien à rapatrier")))
    interaction = _interaction()

    await MemeCog(_bot(tmp_path)).ranger(interaction, _message([
        _piece_jointe(url=f"https://cdn.discordapp.com/a/{nom}", content_type=mime)
    ]))

    dit = interaction.followup.send.call_args.kwargs["content"]
    assert Path(nom).suffix in dit          # le format trouvé est nommé
    assert ".webp" in dit and ".mp4" in dit  # la liste des formats admis y est
    assert "aucune image" not in dit
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_l_apercu_distingue_la_video_de_l_analyse_muette(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_cmd, "telecharger", AsyncMock(return_value=_MP4))
    cog = MemeCog(_bot(tmp_path))
    interaction = _interaction()

    await cog.ranger(interaction, _message([
        _piece_jointe(url="https://cdn/x.mp4", content_type="video/mp4")
    ]))

    dit = interaction.followup.send.call_args.kwargs["content"]
    assert "pas d'analyse possible" in dit and ".mp4" in dit


@pytest.mark.asyncio
async def test_une_image_que_la_vision_ne_decrit_pas_le_dit_franchement(tmp_path, monkeypatch):
    """Annoncer « pas d'analyse pour une vidéo » devant un PNG envoie chercher
    un problème qui n'existe pas."""
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_cmd, "telecharger",
                        AsyncMock(return_value=b"\x89PNG\r\n\x1a\n"))
    bot = _bot(tmp_path)
    bot.vision.analyze = AsyncMock(return_value="")
    interaction = _interaction()

    await MemeCog(bot).ranger(interaction, _message([_piece_jointe()]))

    dit = interaction.followup.send.call_args.kwargs["content"]
    assert "vidéo" not in dit
    assert "n'a rien rendu" in dit


# ── Un message, plusieurs images ──────────────────────────────────────────────
# Un message Discord porte jusqu'à dix fichiers. La commande n'en rangeait qu'un
# et annonçait « 9 autre(s) image(s) laissée(s) » — l'aveu du trou.


def test_toutes_les_images_du_message_sont_rendues():
    embed = MagicMock()
    embed.image.url = "https://media.tenor.com/abc.gif"
    embed.thumbnail.url = None
    message = _message(
        [_piece_jointe(url="https://cdn/a.png"), _piece_jointe(url="https://cdn/b.jpg",
                                                              content_type="image/jpeg")],
        [embed],
    )

    assert meme_cmd.images_du_message(message) == [
        ("https://cdn/a.png", ".png"),
        ("https://cdn/b.jpg", ".jpg"),
        ("https://media.tenor.com/abc.gif", ".gif"),
    ]


def test_le_choix_unitaire_reste_le_premier_format_admis():
    """`image_du_message()` ne change pas de comportement : un `.heic` posté
    avant un `.png` ne prend pas la place du `.png`."""
    message = _message([
        _piece_jointe(url="https://cdn/a.heic", content_type="image/heic"),
        _piece_jointe(url="https://cdn/b.png"),
    ])

    assert image_du_message(message) == ("https://cdn/b.png", ".png")


@pytest.mark.asyncio
async def test_un_message_a_trois_images_les_propose_toutes(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_cmd, "telecharger", AsyncMock(side_effect=[
        _png((1, 2, 3)), _png((4, 5, 6)), _png((7, 8, 9)),
    ]))
    interaction = _interaction()

    await MemeCog(_bot(tmp_path)).ranger(interaction, _message([
        _piece_jointe(url="https://cdn/a.png"),
        _piece_jointe(url="https://cdn/b.png"),
        _piece_jointe(url="https://cdn/c.png"),
    ]))

    contenu = interaction.followup.send.call_args.kwargs["content"]
    assert "3 images" in contenu
    assert "laissée" not in contenu  # plus rien n'est abandonné
    assert list(tmp_path.iterdir()) == []  # toujours rien avant validation


@pytest.mark.asyncio
async def test_ranger_un_lot_ecrit_chaque_image_et_n_annonce_qu_une_fois(tmp_path, monkeypatch):
    """Une annonce par meme noierait le salon : dix embeds à la suite."""
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    salon = _salon()
    vue = VueRangement(42, [
        Entree(_png((1, 2, 3)), ".png", "un carré sombre"),
        Entree(_png((250, 2, 3)), ".png", "un carré rouge"),
        Entree(_MP4, ".mp4", "un clip"),
    ], salon)

    await vue.ranger(_interaction())

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "meme1.webp", "meme1.webp.txt", "meme2.webp", "meme2.webp.txt",
        "meme3.mp4", "meme3.mp4.txt",
    ]
    assert salon.send.await_count == 1
    assert len(salon.send.call_args.kwargs["files"]) == 3


@pytest.mark.asyncio
async def test_un_doublon_dans_le_lot_n_empeche_pas_les_autres(tmp_path, monkeypatch):
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    identique = _png((5, 5, 5))
    vue = VueRangement(42, [
        Entree(identique, ".png", "un carré gris"),
        Entree(identique, ".png", "le même carré gris"),
        Entree(_png((99, 1, 1)), ".png", "un carré rouge"),
    ], _salon())
    interaction = _interaction()

    await vue.ranger(interaction)

    contenu = interaction.response.edit_message.call_args.kwargs["content"]
    assert "2 rangés" in contenu and "1 doublon" in contenu
    assert sorted(p.name for p in tmp_path.glob("*.webp")) == ["meme1.webp", "meme2.webp"]


def test_le_formulaire_n_est_pas_propose_sur_un_lot(tmp_path):
    """« Corriger » ne peut viser qu'une description : à plusieurs, il mentirait."""
    seule = VueRangement(42, [Entree(_PNG, ".png", "un carré")], _salon())
    lot = VueRangement(42, [Entree(_PNG, ".png", "a"), Entree(_MP4, ".mp4", "b")], _salon())

    labels = lambda v: [e.label for e in v.children]
    assert "Corriger" in labels(seule)
    assert "Corriger" not in labels(lot)
    assert "Ranger les 2" in labels(lot)


@pytest.mark.asyncio
async def test_un_lot_ne_paye_la_vision_que_pour_ce_qui_n_est_pas_deja_range(
    tmp_path, monkeypatch
):
    """La dédup passe AVANT la description : décrire un doublon, c'est un appel
    facturé et deux à cinq secondes d'attente pour un fichier qu'on jette."""
    deja = _png((5, 5, 5))
    meme_import.importer(deja, ".png", "déjà là", tmp_path)
    monkeypatch.setattr(meme_cmd, "DOSSIER_MEMES", tmp_path)
    monkeypatch.setattr(meme_cmd, "telecharger", AsyncMock(side_effect=[deja, _png((7, 7, 7))]))
    bot = _bot(tmp_path)

    await MemeCog(bot).ranger(_interaction(), _message([
        _piece_jointe(url="https://cdn/a.png"), _piece_jointe(url="https://cdn/b.png"),
    ]))

    assert bot.vision.analyze.await_count == 1
