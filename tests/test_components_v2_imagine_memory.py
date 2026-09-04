"""`/wally imagine` et `/wally memory` en Components V2.

Les deux fiches sont passées de l'embed au `Container`. Ce que ces tests
tiennent, ce sont les trois choses que la bascule casse en SILENCE :

· un message ne peut pas devenir V2 après coup s'il porte un embed — d'où la
  carte de chargement déjà en V2 ;
· le plafond de texte d'un message V2 est de 4000 caractères, tous
  `TextDisplay` confondus, là où une description d'embed en tenait 4096 ;
· un clic reste traité UNE fois, par le listener, jamais aussi par un callback.
"""
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.discord.commands.imagine import (
    EditTitleButton,
    FlameButton,
    ImagineCog,
    VueChargement,
    VueGalerie,
    _nom_piece_jointe,
    vue_depuis_base,
)
from bot.discord.commands.memory_cmd import VueMemoire

_PLAFOND_TEXTE_V2 = 4000


def _textes(vue: discord.ui.LayoutView) -> list[str]:
    return [i.content for i in vue.walk_children()
            if isinstance(i, discord.ui.TextDisplay)]


def _boutons(vue: discord.ui.LayoutView) -> list[discord.ui.Button]:
    return [i for i in vue.walk_children() if isinstance(i, discord.ui.Button)]


# ── /imagine ─────────────────────────────────────────────────────────────────

def test_la_carte_de_chargement_est_deja_en_v2():
    """Le drapeau `IS_COMPONENTS_V2` s'ajoute à l'édition mais ne se RETIRE plus,
    et Discord refuse un message V2 qui garde un embed : partir d'un embed de
    chargement rendrait l'édition finale impossible."""
    vue = VueChargement("Wally peint", "un chat", "Az", gif=True)
    assert vue.has_components_v2()
    assert any(isinstance(i, discord.ui.MediaGallery) for i in vue.walk_children())


def test_la_carte_sans_gif_tient_quand_meme():
    vue = VueChargement("Wally peint", "un chat", "Az", gif=False)
    assert not any(isinstance(i, discord.ui.MediaGallery) for i in vue.walk_children())
    assert any("un chat" in t for t in _textes(vue))


def test_les_boutons_vivent_dans_le_conteneur():
    vue = VueGalerie("img1", "Titre", "un prompt", "Az", "image.png", 3)
    assert isinstance(vue.children[0], discord.ui.Container)
    ids = [b.custom_id for b in _boutons(vue)]
    assert ids == ["gallery_vote:img1", "gallery_edit:img1"]


def test_le_compteur_de_flammes_est_le_libelle():
    """Le style ne dit RIEN du vote : sur un message partagé, un bouton rouge
    annoncerait aux autres un vote qui n'est pas le leur."""
    vue = VueGalerie("img1", "T", "p", "Az", "image.png", 7)
    flamme = _boutons(vue)[0]
    assert flamme.label == "7"
    assert flamme.style is discord.ButtonStyle.secondary


def test_la_piece_jointe_se_rededuit_du_chemin_en_base():
    assert _nom_piece_jointe("abc123.webp") == "image.webp"
    assert _nom_piece_jointe("abc123.png") == "image.png"
    assert _nom_piece_jointe("sans_extension") == "image.png"


def test_la_carte_se_rebatit_depuis_la_base():
    """Après un rebuild, le process qui traite le clic n'a jamais vu l'image :
    tout ce qu'il redessine vient de la ligne en base."""
    vue = vue_depuis_base({
        "id": "img42", "title": "Le chat", "prompt": "un chat roux",
        "username": "Az", "file_path": "abc.webp", "votes": 2,
    })
    assert "## Le chat" in _textes(vue)
    assert _boutons(vue)[0].label == "2"
    galerie = next(i for i in vue.walk_children()
                   if isinstance(i, discord.ui.MediaGallery))
    assert galerie.items[0].media.url == "attachment://image.webp"


def test_les_boutons_de_galerie_nont_pas_de_callback_propre():
    """Le seul chemin de traitement est `ImagineCog.on_interaction` : un
    callback en plus ferait basculer le vote deux fois, net zéro."""
    assert FlameButton.callback is discord.ui.Item.callback
    assert EditTitleButton.callback is discord.ui.Item.callback


async def test_un_clic_ne_bascule_le_vote_quune_fois():
    db = MagicMock()
    db.toggle_gallery_vote = AsyncMock(return_value=True)
    db.get_gallery_image = AsyncMock(return_value={
        "id": "img42", "title": "T", "prompt": "p", "username": "Az",
        "file_path": "abc.png", "votes": 1, "user_id": "discord:610",
    })
    bot = MagicMock()
    bot.db = db
    cog = ImagineCog(bot)

    interaction = MagicMock()
    interaction.type = discord.InteractionType.component
    interaction.data = {"custom_id": "gallery_vote:img42"}
    interaction.user.id = 610
    interaction.response.edit_message = AsyncMock()

    # Le clic tel que discord.py le livre : la vue ne fait rien, le listener agit.
    vue = vue_depuis_base(await db.get_gallery_image("img42"))
    await _boutons(vue)[0].callback(interaction)     # dispatch_view → no-op
    await cog.on_interaction(interaction)            # dispatch('interaction')

    assert db.toggle_gallery_vote.await_count == 1
    envoyee = interaction.response.edit_message.await_args.kwargs["view"]
    assert _boutons(envoyee)[0].label == "1"


async def test_une_image_effacee_ne_redessine_pas_une_carte_inventee():
    db = MagicMock()
    db.toggle_gallery_vote = AsyncMock(return_value=True)
    db.get_gallery_image = AsyncMock(return_value=None)
    bot = MagicMock()
    bot.db = db
    cog = ImagineCog(bot)

    interaction = MagicMock()
    interaction.type = discord.InteractionType.component
    interaction.data = {"custom_id": "gallery_vote:disparue"}
    interaction.user.id = 610
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()

    await cog.on_interaction(interaction)
    interaction.response.edit_message.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


# ── /memory ──────────────────────────────────────────────────────────────────

def test_les_scores_de_relation_survivent_au_changement_de_page():
    """Ils étaient COLLÉS en tête du texte paginé : ils vivaient dans la page 1
    et disparaissaient dès qu'on tournait la page."""
    vue = VueMemoire(["page une", "page deux"], "Az", 0.42, 0.13)
    assert any("Confiance : 0.42" in t and "Affection : 0.13" in t
               for t in _textes(vue))
    suivante = VueMemoire(vue.pages, vue.user_name, vue.trust, vue.love, page=1)
    assert any("Confiance : 0.42" in t for t in _textes(suivante))
    assert "page deux" in _textes(suivante)


def test_une_seule_page_na_pas_de_fleches():
    assert _boutons(VueMemoire(["tout tient"], "Az", 0.0, 0.0)) == []


async def test_les_fleches_bornent_la_pagination():
    vue = VueMemoire(["a", "b", "c"], "Az", 0.0, 0.0)
    gauche, droite = _boutons(vue)
    assert gauche.disabled and not droite.disabled

    interaction = MagicMock()
    interaction.response.edit_message = AsyncMock()
    await droite.callback(interaction)
    suivante = interaction.response.edit_message.await_args.kwargs["view"]
    assert "b" in _textes(suivante)
    assert not _boutons(suivante)[0].disabled

    fin = VueMemoire(["a", "b", "c"], "Az", 0.0, 0.0, page=2)
    assert _boutons(fin)[1].disabled


def test_une_page_tient_sous_le_plafond_de_texte_dun_message_v2():
    """4000 caractères pour TOUS les `TextDisplay` d'un message, là où une
    description d'embed en tenait 4096 à elle seule."""
    from bot.discord.commands.memory_cmd import _PAGE_SIZE, _paginate

    pages = _paginate("\n".join(f"- souvenir numéro {i}" for i in range(500)))
    assert all(len(p) <= _PAGE_SIZE for p in pages)
    vue = VueMemoire(pages, "Azraël-au-nom-très-long", 0.99, 0.99)
    assert sum(len(t) for t in _textes(vue)) <= _PLAFOND_TEXTE_V2
