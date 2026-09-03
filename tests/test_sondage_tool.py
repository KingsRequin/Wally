"""L'outil `sondage` : ce que Wally a le droit de faire, et pour qui."""
from __future__ import annotations

from types import SimpleNamespace

import discord

import pytest

from bot.discord.sondage_service import SONDAGE_TOOL, SondageService, run_sondage_tool
from tests.test_sondage_service import FauxSalon


class FauxDroits:
    def __init__(self, *, ecrire=True, ping=False) -> None:
        self.send_messages = ecrire
        self.mention_everyone = ping


class SalonDroits(FauxSalon):
    def __init__(self, nom="general", salon_id=42, *, auteur=None, moi=None) -> None:
        super().__init__(salon_id)
        self.name = nom
        self.guild = None
        self._auteur = auteur or FauxDroits()
        self._moi = moi or FauxDroits(ping=True)

    def permissions_for(self, membre):
        return self._moi if getattr(membre, "est_wally", False) else self._auteur


class FauxGuild:
    def __init__(self, salons) -> None:
        self.text_channels = salons
        self.me = SimpleNamespace(id=99, est_wally=True)
        for salon in salons:
            salon.guild = self

    def get_channel(self, salon_id):
        return next((s for s in self.text_channels if s.id == salon_id), None)


class FauxBotOutil:
    def __init__(self, guild) -> None:
        self.db = None
        self.user = SimpleNamespace(id=99)
        self.guild = guild

    def get_channel(self, salon_id):
        return self.guild.get_channel(salon_id)


@pytest.fixture
def monde(monkeypatch):
    ici = SalonDroits("general", 42)
    ailleurs = SalonDroits("annonces", 43)
    guild = FauxGuild([ici, ailleurs])
    bot = FauxBotOutil(guild)
    service = SondageService(bot)
    monkeypatch.setattr(service, "DELAI_MAJ_S", 0.01)
    bot.sondages = service
    message = SimpleNamespace(
        channel=ici, guild=guild,
        author=SimpleNamespace(id=7, display_name="Azraël", est_wally=False))
    return SimpleNamespace(bot=bot, service=service, ici=ici, ailleurs=ailleurs,
                           message=message)


async def _lancer(monde, **args):
    args.setdefault("action", "creer")
    args.setdefault("question", "Quel jeu ?")
    args.setdefault("options", ["Apex", "Rocket League"])
    return await run_sondage_tool(monde.bot, args, message=monde.message)


# ── forme de l'outil ────────────────────────────────────────────────────────

def test_la_spec_est_au_format_openai():
    fonction = SONDAGE_TOOL["function"]
    assert SONDAGE_TOOL["type"] == "function"
    assert fonction["name"] == "sondage"
    assert set(fonction["parameters"]["properties"]) == {
        "action", "question", "options", "duree_minutes", "salon", "ping_everyone"}


# ── création ────────────────────────────────────────────────────────────────

async def test_le_sondage_part_dans_le_salon_courant(monde):
    rendu = await _lancer(monde)
    assert monde.ici.envois and not monde.ailleurs.envois
    assert "sondage" in rendu.lower()


async def test_moins_de_deux_options_est_refuse(monde):
    rendu = await _lancer(monde, options=["seule"])
    assert not monde.ici.envois
    assert "deux" in rendu.lower()


async def test_la_duree_en_minutes_devient_une_echeance(monde):
    await _lancer(monde, duree_minutes=5)
    sondage = monde.service.sondages.ouvert_dans(42)
    assert sondage is not None and sondage.duree_s == 300


async def test_une_duree_absurde_est_bornee(monde):
    await _lancer(monde, duree_minutes=99_999)
    sondage = monde.service.sondages.ouvert_dans(42)
    assert sondage is not None and sondage.duree_s == 24 * 3600


async def test_un_seul_sondage_ouvert_par_salon(monde):
    await _lancer(monde)
    rendu = await _lancer(monde, question="Un autre ?")
    assert len(monde.ici.envois) == 1
    assert "déjà" in rendu.lower()


# ── ping @everyone ──────────────────────────────────────────────────────────

async def test_ping_everyone_quand_le_demandeur_en_a_le_droit(monde):
    monde.ici._auteur = FauxDroits(ping=True)
    await _lancer(monde, ping_everyone=True)
    vue = monde.ici.envois[0]["view"]
    assert any("@everyone" in c.content for c in vue.walk_children()
               if isinstance(c, discord.ui.TextDisplay))


async def test_sans_le_droit_le_sondage_part_mais_sans_ping(monde):
    """Le sondage est ce qu'on a demandé ; le ping est un supplément. On ne
    perd pas le premier à cause du second — mais Wally DIT pourquoi."""
    rendu = await _lancer(monde, ping_everyone=True)
    assert not (monde.ici.envois[0]["content"] or "")
    assert "everyone" in rendu.lower() and "droit" in rendu.lower()


async def test_wally_ne_ping_pas_s_il_n_en_a_pas_le_droit_lui_meme(monde):
    monde.ici._auteur = FauxDroits(ping=True)
    monde.ici._moi = FauxDroits(ping=False)
    await _lancer(monde, ping_everyone=True)
    assert not (monde.ici.envois[0]["content"] or "")


# ── autre salon ─────────────────────────────────────────────────────────────

async def test_poster_dans_un_autre_salon_par_son_nom(monde):
    await _lancer(monde, salon="annonces")
    assert monde.ailleurs.envois and not monde.ici.envois


async def test_poster_dans_un_autre_salon_par_sa_mention(monde):
    await _lancer(monde, salon="<#43>")
    assert monde.ailleurs.envois


async def test_un_salon_inconnu_est_refuse(monde):
    rendu = await _lancer(monde, salon="nexistepas")
    assert not monde.ici.envois and not monde.ailleurs.envois
    assert "nexistepas" in rendu


async def test_un_salon_interdit_au_demandeur_est_refuse(monde):
    """Poster ailleurs PAR PROCURATION : ce que Wally ne doit jamais permettre."""
    monde.ailleurs._auteur = FauxDroits(ecrire=False)
    rendu = await _lancer(monde, salon="annonces")
    assert not monde.ailleurs.envois
    assert "droit" in rendu.lower()


async def test_un_salon_ou_wally_ne_peut_pas_ecrire_est_refuse(monde):
    monde.ailleurs._moi = FauxDroits(ecrire=False)
    rendu = await _lancer(monde, salon="annonces")
    assert not monde.ailleurs.envois and rendu


# ── clôture ─────────────────────────────────────────────────────────────────

async def test_fermer_depouille_le_sondage_du_salon(monde):
    await _lancer(monde)
    rendu = await _lancer(monde, action="fermer")
    assert all(b.disabled for b in monde.ici.message.editions[-1]["view"].walk_children()
               if isinstance(b, discord.ui.Button))
    assert "Apex" in rendu or "aucun vote" in rendu.lower()


async def test_fermer_sans_sondage_ouvert_le_dit(monde):
    rendu = await _lancer(monde, action="fermer")
    assert "aucun sondage" in rendu.lower()


async def test_fermer_vise_le_salon_demande(monde):
    await _lancer(monde, salon="annonces")
    await _lancer(monde, action="fermer", salon="annonces")
    assert all(b.disabled for b in monde.ailleurs.message.editions[-1]["view"].walk_children()
               if isinstance(b, discord.ui.Button))
