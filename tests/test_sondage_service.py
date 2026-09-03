"""Le sondage Discord de bout en bout : envoi, vote, clôture, reprise.

La carte est en Components V2 : on inspecte donc la VUE (`walk_children`) là où
ces tests lisaient un embed, et on simule un clic de bouton là où ils posaient
une réaction.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot.core.sondage import EMOJIS_VOTE, MAX_OPTIONS
from bot.discord.sondage_service import SondageService, vue_de_routage


class FauxMessage:
    def __init__(self, salon, message_id: int = 1234) -> None:
        self.id = message_id
        self.channel = salon
        self.editions: list[dict] = []

    async def edit(self, **kwargs) -> None:
        self.editions.append(kwargs)


class FauxSalon:
    def __init__(self, salon_id: int = 42) -> None:
        self.id = salon_id
        self.envois: list[dict] = []
        self.message = FauxMessage(self)

    async def send(self, content=None, **kwargs):
        self.envois.append({"content": content, **kwargs})
        return self.message

    def get_partial_message(self, message_id: int):
        return self.message

    async def fetch_message(self, message_id: int):
        return self.message


class FauxBot:
    def __init__(self, salon: FauxSalon) -> None:
        self.db = None
        self.user = SimpleNamespace(id=99)
        self._salon = salon

    def get_channel(self, salon_id: int):
        return self._salon if salon_id == self._salon.id else None


class FausseReponse:
    def __init__(self) -> None:
        self.deferee = False
        self.messages: list[str] = []

    async def defer(self) -> None:
        self.deferee = True

    async def send_message(self, contenu: str, **_kw) -> None:
        self.messages.append(contenu)


class FausseInteraction:
    def __init__(self, message, user_id: int = 7) -> None:
        self.message = message
        self.user = SimpleNamespace(id=user_id)
        self.response = FausseReponse()


@pytest.fixture
def salon() -> FauxSalon:
    return FauxSalon()


@pytest.fixture
def service(salon, monkeypatch) -> SondageService:
    svc = SondageService(FauxBot(salon))
    monkeypatch.setattr(svc, "DELAI_MAJ_S", 0.01)
    return svc


async def _creer(service, salon, **kw):
    sondage = await service.creer(
        salon=salon, question=kw.pop("question", "Quel jeu ?"),
        options=kw.pop("options", ["Apex", "Rocket League"]),
        auteur=kw.pop("auteur", "Azraël"), **kw)
    assert sondage is not None
    return sondage


async def _cliquer(service, salon, index: int, user_id: int = 7) -> FausseInteraction:
    interaction = FausseInteraction(salon.message, user_id=user_id)
    await service.sur_clic(interaction, index)
    return interaction


def _boutons(vue) -> list[discord.ui.Button]:
    return [c for c in vue.walk_children() if isinstance(c, discord.ui.Button)]


def _textes(vue) -> list[str]:
    return [c.content for c in vue.walk_children()
            if isinstance(c, discord.ui.TextDisplay)]


def _derniere_vue(salon):
    return salon.message.editions[-1]["view"]


# ── envoi ───────────────────────────────────────────────────────────────────

async def test_creer_envoie_une_carte_avec_un_bouton_par_option(service, salon):
    await _creer(service, salon, options=["a", "b", "c"])
    assert len(salon.envois) == 1
    boutons = _boutons(salon.envois[0]["view"])
    assert [b.label for b in boutons] == ["a", "b", "c"]
    assert [b.emoji.name for b in boutons] == list(EMOJIS_VOTE[:3])


async def test_la_carte_porte_la_question_et_l_image(service, salon):
    """La question EN TEXTE, pas seulement dans l'image : c'est elle qui part en
    notification et en aperçu mobile, là où un PNG ne dit rien."""
    await _creer(service, salon, question="On joue à quoi ?")
    envoi = salon.envois[0]
    assert any("On joue à quoi ?" in t for t in _textes(envoi["view"]))
    galeries = [c for c in envoi["view"].walk_children()
                if isinstance(c, discord.ui.MediaGallery)]
    assert galeries and galeries[0].items[0].media.url == "attachment://sondage.png"
    assert envoi["file"].filename == "sondage.png"


async def test_la_carte_ne_passe_aucun_content(service, salon):
    """Components V2 refuse `content` : le message entier vit dans la vue."""
    await _creer(service, salon)
    assert salon.envois[0]["content"] is None


async def test_sans_ping_rien_n_est_mentionne(service, salon):
    await _creer(service, salon)
    envoi = salon.envois[0]
    assert not any("@everyone" in t for t in _textes(envoi["view"]))
    assert envoi["allowed_mentions"].everyone is False


async def test_avec_ping_everyone_est_mentionne(service, salon):
    """Le ping voyage dans un TextDisplay — `content` étant interdit."""
    await _creer(service, salon, ping=True)
    envoi = salon.envois[0]
    assert any("@everyone" in t for t in _textes(envoi["view"]))
    assert envoi["allowed_mentions"].everyone is True


async def test_le_sondage_est_retrouvable_par_son_message(service, salon):
    sondage = await _creer(service, salon)
    assert service.sondages.par_message(salon.message.id) is sondage


async def test_neuf_options_tiennent_en_deux_rangs(service, salon):
    """Une `ActionRow` plafonne à cinq boutons : au-delà, il en faut une autre."""
    await _creer(service, salon, options=[str(i) for i in range(MAX_OPTIONS)])
    rangs = [c for c in salon.envois[0]["view"].walk_children()
             if isinstance(c, discord.ui.ActionRow)]
    assert len(rangs) == 2
    assert len(_boutons(salon.envois[0]["view"])) == MAX_OPTIONS


# ── vote ────────────────────────────────────────────────────────────────────

async def test_un_vote_redessine_le_message(service, salon):
    await _creer(service, salon)
    interaction = await _cliquer(service, salon, 0)
    await asyncio.sleep(0.05)
    assert interaction.response.deferee, "le clic n'a pas été accusé"
    assert salon.message.editions, "le message n'a jamais été redessiné"


async def test_deux_votes_rapproches_ne_font_qu_une_edition(service, salon):
    """Discord limite les éditions : une rafale de votes doit se fondre en une."""
    await _creer(service, salon)
    for uid in (7, 8, 9):
        await _cliquer(service, salon, 0, user_id=uid)
    await asyncio.sleep(0.05)
    assert len(salon.message.editions) == 1


async def test_changer_d_avis_remplace_le_vote(service, salon):
    """La demande de l'owner : le premier vote est annulé, pas cumulé. Aucun
    retrait de réaction n'est nécessaire — donc plus besoin de `Gérer les
    messages`, qui manquait sur la moitié des salons."""
    sondage = await _creer(service, salon)
    await _cliquer(service, salon, 0)
    await _cliquer(service, salon, 1)
    await asyncio.sleep(0.05)
    assert sondage.depouiller().tally == [0, 1]


async def test_recliquer_son_choix_retire_sa_voix(service, salon):
    sondage = await _creer(service, salon)
    await _cliquer(service, salon, 0)
    await _cliquer(service, salon, 0)
    await asyncio.sleep(0.05)
    assert sondage.depouiller().total == 0


async def test_un_clic_hors_sondage_le_dit_sans_rien_redessiner(service, salon):
    interaction = await _cliquer(service, salon, 0)   # aucun sondage créé
    await asyncio.sleep(0.05)
    assert interaction.response.messages, "le clic est resté sans réponse"
    assert not salon.message.editions


async def test_une_option_inexistante_est_refusee(service, salon):
    """La vue de routage porte les neuf boutons : un client retardataire peut
    envoyer un index que ce sondage-ci ne propose pas."""
    sondage = await _creer(service, salon, options=["a", "b"])
    interaction = await _cliquer(service, salon, 8)
    assert interaction.response.messages
    assert sondage.depouiller().total == 0


# ── clôture ─────────────────────────────────────────────────────────────────

async def test_la_cloture_grise_les_boutons_et_annonce_le_resultat(service, salon):
    sondage = await _creer(service, salon)
    await _cliquer(service, salon, 0)
    await service.fermer(sondage)
    assert sondage.clos
    vue = _derniere_vue(salon)
    assert all(b.disabled for b in _boutons(vue))
    assert any("Apex" in t for t in _textes(vue))


async def test_un_sondage_clos_ne_prend_plus_de_vote(service, salon):
    sondage = await _creer(service, salon)
    await service.fermer(sondage)
    editions = len(salon.message.editions)
    interaction = await _cliquer(service, salon, 0)
    await asyncio.sleep(0.05)
    assert sondage.depouiller().total == 0
    assert len(salon.message.editions) == editions
    assert interaction.response.messages, "le clic tardif est resté sans réponse"


async def test_la_duree_ferme_le_sondage_toute_seule(service, salon):
    sondage = await _creer(service, salon, duree_s=0.02)
    await asyncio.sleep(0.15)
    assert sondage.clos


async def test_fermer_deux_fois_ne_casse_rien(service, salon):
    sondage = await _creer(service, salon)
    await service.fermer(sondage)
    editions = len(salon.message.editions)
    await service.fermer(sondage)
    assert len(salon.message.editions) == editions


# ── reprise après redémarrage ───────────────────────────────────────────────

async def test_la_vue_de_routage_est_persistante(service):
    """Le point qui décide de tout après un rebuild : sans vue persistante,
    Discord répond « Cette interaction a échoué » sur les boutons déjà publiés,
    et rien dans les logs ne le dirait."""
    vue = vue_de_routage()
    assert vue.is_persistent()
    ids = [b.custom_id for b in _boutons(vue)]
    assert ids == [f"sondage:vote:{i}" for i in range(MAX_OPTIONS)]


async def test_la_reprise_relit_les_votes_ranges(service, salon):
    """Un bouton ne laisse rien sur le message, contrairement à une réaction :
    l'état rangé est la SEULE source de vérité au redémarrage."""
    sondage = await _creer(service, salon, duree_s=600)
    await _cliquer(service, salon, 1, user_id=3)
    await _cliquer(service, salon, 1, user_id=4)
    await asyncio.sleep(0.05)

    repris = SondageService(FauxBot(salon))
    repris.sondages.from_dict(service.sondages.to_dict())
    await repris.reprendre()
    retrouve = repris.sondages.par_message(salon.message.id)
    assert retrouve is not None
    assert retrouve.depouiller().tally == [0, 2]
    assert sondage.question == retrouve.question


async def test_la_reprise_ferme_un_sondage_echu_pendant_la_coupure(service, salon):
    sondage = await _creer(service, salon, duree_s=600)
    sondage.ends_at = 1.0                      # échéance largement dépassée

    repris = SondageService(FauxBot(salon))
    repris.sondages.from_dict(service.sondages.to_dict())
    await repris.reprendre()
    assert all(b.disabled for b in _boutons(_derniere_vue(salon)))


async def test_la_reprise_oublie_un_message_disparu(service, salon, monkeypatch):
    """Message supprimé pendant la coupure : le sondage n'a plus de support."""
    await _creer(service, salon, duree_s=600)

    async def _introuvable(_message_id):
        raise discord.NotFound(SimpleNamespace(status=404, reason=""), "parti")

    repris = SondageService(FauxBot(salon))
    repris.sondages.from_dict(service.sondages.to_dict())
    monkeypatch.setattr(salon, "fetch_message", _introuvable)
    await repris.reprendre()
    assert repris.sondages.ouverts() == []


async def test_un_message_supprime_libere_le_salon(service, salon, monkeypatch):
    """Sans ça, un sondage sans support bloquerait tous les suivants du salon."""
    sondage = await _creer(service, salon)

    async def _disparu(**_kwargs):
        raise discord.NotFound(SimpleNamespace(status=404, reason=""), "parti")

    monkeypatch.setattr(salon.message, "edit", _disparu)
    await _cliquer(service, salon, 0)
    await asyncio.sleep(0.05)
    assert service.sondages.ouvert_dans(salon.id) is None
    assert sondage.clos
