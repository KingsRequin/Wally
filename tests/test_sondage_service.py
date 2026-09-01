"""Le sondage Discord de bout en bout : envoi, vote, clôture, reprise."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot.core.sondage import EMOJIS_VOTE
from bot.discord.sondage_service import SondageService


class FausseReaction:
    def __init__(self, emoji: str, users: list[int]) -> None:
        self.emoji = emoji
        self._users = users

    def users(self):
        async def _gen():
            for uid in self._users:
                yield SimpleNamespace(id=uid, bot=False)
        return _gen()


class FauxMessage:
    def __init__(self, salon, message_id: int = 1234) -> None:
        self.id = message_id
        self.channel = salon
        self.reactions: list[FausseReaction] = []
        self.editions: list[dict] = []
        self.retirees: list[tuple[str, int]] = []
        self.nettoyee = False
        self.emojis_poses: list[str] = []
        self.echec_retrait: Exception | None = None

    async def edit(self, **kwargs) -> None:
        self.editions.append(kwargs)

    async def add_reaction(self, emoji: str) -> None:
        self.emojis_poses.append(emoji)

    async def remove_reaction(self, emoji, membre) -> None:
        if self.echec_retrait is not None:
            raise self.echec_retrait
        self.retirees.append((str(emoji), membre.id))

    async def clear_reactions(self) -> None:
        self.nettoyee = True


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


class _Emoji:
    def __init__(self, valeur: str) -> None:
        self.valeur = valeur

    def __str__(self) -> str:
        return self.valeur


def _payload_reel(message, emoji: str, user_id: int = 7):
    return SimpleNamespace(message_id=message.id, channel_id=message.channel.id,
                           user_id=user_id, emoji=_Emoji(emoji),
                           member=SimpleNamespace(id=user_id, bot=False))


# ── envoi ───────────────────────────────────────────────────────────────────

async def test_creer_envoie_l_embed_et_pose_une_reaction_par_option(service, salon):
    await _creer(service, salon, options=["a", "b", "c"])
    assert len(salon.envois) == 1
    assert salon.message.emojis_poses == list(EMOJIS_VOTE[:3])


async def test_l_embed_porte_la_question_et_l_image(service, salon):
    """La question DANS l'embed, pas seulement dans l'image : c'est elle qui
    apparaît en notification et en aperçu mobile."""
    await _creer(service, salon, question="On joue à quoi ?")
    envoi = salon.envois[0]
    assert envoi["embed"].title == "On joue à quoi ?"
    assert envoi["embed"].image.url == "attachment://sondage.png"
    assert envoi["file"].filename == "sondage.png"


async def test_sans_ping_rien_n_est_mentionne(service, salon):
    await _creer(service, salon)
    envoi = salon.envois[0]
    assert not envoi["content"]
    assert envoi["allowed_mentions"].everyone is False


async def test_avec_ping_everyone_est_mentionne(service, salon):
    await _creer(service, salon, ping=True)
    envoi = salon.envois[0]
    assert "@everyone" in envoi["content"]
    assert envoi["allowed_mentions"].everyone is True


async def test_le_sondage_est_retrouvable_par_son_message(service, salon):
    sondage = await _creer(service, salon)
    assert service.sondages.par_message(salon.message.id) is sondage


# ── vote ────────────────────────────────────────────────────────────────────

async def test_un_vote_redessine_le_message(service, salon):
    await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await asyncio.sleep(0.05)
    assert salon.message.editions, "le message n'a jamais été redessiné"


async def test_deux_votes_rapproches_ne_font_qu_une_edition(service, salon):
    """Discord limite les éditions : une rafale de votes doit se fondre en une."""
    await _creer(service, salon)
    for uid in (7, 8, 9):
        await service.sur_reaction(
            _payload_reel(salon.message, EMOJIS_VOTE[0], user_id=uid), ajout=True)
    await asyncio.sleep(0.05)
    assert len(salon.message.editions) == 1


async def test_changer_d_avis_retire_l_ancienne_reaction(service, salon):
    """La demande de l'owner : le premier vote est annulé, pas cumulé."""
    sondage = await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[1]), ajout=True)
    await asyncio.sleep(0.05)
    assert salon.message.retirees == [(EMOJIS_VOTE[0], 7)]
    assert sondage.depouiller().tally == [0, 1]


async def test_sans_droit_de_retrait_le_premier_vote_fait_foi(service, salon):
    """Sans `Gérer les messages`, retirer la réaction d'autrui est impossible :
    on ne peut pas laisser deux réactions compter pour deux voix."""
    salon.message.echec_retrait = discord.Forbidden(
        SimpleNamespace(status=403, reason=""), "nope")
    sondage = await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[1]), ajout=True)
    assert sondage.depouiller().tally == [1, 0]


async def test_la_reaction_de_wally_est_ignoree(service, salon):
    """Il pose lui-même les chiffres : sans ça, chaque sondage démarre avec une
    voix pour chaque option."""
    sondage = await _creer(service, salon)
    await service.sur_reaction(
        _payload_reel(salon.message, EMOJIS_VOTE[0], user_id=99), ajout=True)
    assert sondage.depouiller().total == 0


async def test_une_reaction_etrangere_ne_redessine_pas(service, salon):
    await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, "🍕"), ajout=True)
    await asyncio.sleep(0.05)
    assert not salon.message.editions


async def test_une_reaction_hors_sondage_est_ignoree(service, salon):
    payload = _payload_reel(salon.message, EMOJIS_VOTE[0])
    await service.sur_reaction(payload, ajout=True)   # aucun sondage créé
    assert not salon.message.editions


async def test_retirer_sa_reaction_retire_son_vote(service, salon):
    sondage = await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=False)
    await asyncio.sleep(0.05)
    assert sondage.depouiller().total == 0


async def test_le_retrait_fait_par_wally_ne_defait_pas_le_nouveau_vote(service, salon):
    """Retirer une réaction déclenche l'événement de retrait : sans garde, le
    changement d'avis s'annulerait lui-même."""
    sondage = await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[1]), ajout=True)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=False)
    assert sondage.depouiller().tally == [0, 1]


# ── clôture ─────────────────────────────────────────────────────────────────

async def test_la_cloture_nettoie_les_reactions_et_annonce_le_resultat(service, salon):
    sondage = await _creer(service, salon)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await service.fermer(sondage)
    assert sondage.clos and salon.message.nettoyee
    assert "Apex" in salon.message.editions[-1]["embed"].description


async def test_un_sondage_clos_ne_prend_plus_de_vote(service, salon):
    sondage = await _creer(service, salon)
    await service.fermer(sondage)
    editions = len(salon.message.editions)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await asyncio.sleep(0.05)
    assert sondage.depouiller().total == 0
    assert len(salon.message.editions) == editions


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

async def test_la_reprise_recompte_depuis_les_reactions(service, salon):
    """Les votes posés pendant que le process était éteint n'ont produit aucun
    événement : seul le message les porte."""
    sondage = await _creer(service, salon, duree_s=600)
    salon.message.reactions = [FausseReaction(EMOJIS_VOTE[1], [3, 4])]

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
    assert salon.message.nettoyee


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


# ── ce qu'un vote N'EST PAS ─────────────────────────────────────────────────

async def test_un_vote_se_declare_comme_tel(service, salon):
    """Le booléen commande l'arrêt du handler : sans lui, trente votants sur un
    sondage de Wally lui font un pic de joie et trente lignes de perception."""
    await _creer(service, salon)
    assert await service.sur_reaction(
        _payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True) is True


async def test_une_reaction_ordinaire_n_est_pas_un_vote(service, salon):
    await _creer(service, salon)
    assert await service.sur_reaction(
        _payload_reel(salon.message, "😂"), ajout=True) is False


async def test_un_message_supprime_libere_le_salon(service, salon, monkeypatch):
    """Sans ça, un sondage sans support bloquerait tous les suivants du salon."""
    sondage = await _creer(service, salon)

    async def _disparu(**_kwargs):
        raise discord.NotFound(SimpleNamespace(status=404, reason=""), "parti")

    monkeypatch.setattr(salon.message, "edit", _disparu)
    await service.sur_reaction(_payload_reel(salon.message, EMOJIS_VOTE[0]), ajout=True)
    await asyncio.sleep(0.05)
    assert service.sondages.ouvert_dans(salon.id) is None
    assert sondage.clos
