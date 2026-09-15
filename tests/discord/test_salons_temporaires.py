from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.discord import salons_temporaires as st

CREATEUR = 500


class _Membre(SimpleNamespace):
    """Membre Discord factice, hashable comme un vrai `discord.Member`
    (mixin Snowflake). `SimpleNamespace` ne l'est pas : définir `__eq__` lui
    retire `__hash__`, et `overwrites={member: ...}` a besoin d'une clé
    hashable."""

    def __hash__(self):
        return hash(self.id)


class FauxDb:
    def __init__(self, ids=()):
        self.ids = set(ids)

    async def salon_temporaire_ajouter(self, channel_id, guild_id):
        self.ids.add(channel_id)

    async def salon_temporaire_retirer(self, channel_id):
        self.ids.discard(channel_id)

    async def salons_temporaires(self):
        return set(self.ids)


def _bot(db, createur=CREATEUR, noms=("Arène des Apex",)):
    cfg = SimpleNamespace(salon_createur_id=createur, noms=list(noms))
    journal = SimpleNamespace(salon_id=None, guild_ids=[])
    bot = SimpleNamespace(
        db=db,
        config=SimpleNamespace(discord=SimpleNamespace(salons_temporaires=cfg,
                                                        journal_moderation=journal)),
        salons={},
    )
    bot.get_channel = lambda cid: bot.salons.get(cid)
    return bot


def _salon(cid, membres=(), guild=SimpleNamespace(id=9), category="cat"):
    s = SimpleNamespace(id=cid, name=f"s{cid}", members=list(membres),
                        guild=guild, category=category)
    s.delete = AsyncMock()
    return s


def _etat(salon):
    return SimpleNamespace(channel=salon)


async def test_entrer_dans_le_createur_cree_enregistre_et_deplace():
    nouveau = _salon(777, guild=SimpleNamespace(id=9))
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(return_value=nouveau))
    createur = _salon(CREATEUR, guild=guild)
    membre = _Membre(id=1, bot=False, move_to=AsyncMock(), display_name="A", name="A")
    db = FauxDb()

    await st.sur_changement_vocal(_bot(db), membre, _etat(None), _etat(createur))

    kwargs = guild.create_voice_channel.await_args.kwargs
    assert guild.create_voice_channel.await_args.args[0] == "Arène des Apex"
    assert kwargs["category"] == "cat"
    assert kwargs["overwrites"][membre].manage_channels is True
    assert db.ids == {777}
    membre.move_to.assert_awaited_once_with(nouveau)


async def test_un_bot_qui_entre_dans_le_createur_ne_cree_rien():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock())
    membre = SimpleNamespace(id=1, bot=True, move_to=AsyncMock())
    await st.sur_changement_vocal(_bot(FauxDb()), membre, _etat(None),
                                  _etat(_salon(CREATEUR, guild=guild)))
    guild.create_voice_channel.assert_not_awaited()


async def test_deplacement_rate_supprime_le_salon_cree():
    nouveau = _salon(777)
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(return_value=nouveau))
    membre = _Membre(id=1, bot=False, display_name="A",
                     move_to=AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "parti")))
    db = FauxDb()
    await st.sur_changement_vocal(_bot(db), membre, _etat(None),
                                  _etat(_salon(CREATEUR, guild=guild)))
    nouveau.delete.assert_awaited_once()
    assert db.ids == set()


async def test_quitter_un_salon_gere_vide_le_supprime():
    salon = _salon(777, membres=[])
    db = FauxDb({777})
    membre = SimpleNamespace(id=1, bot=False)
    await st.sur_changement_vocal(_bot(db), membre, _etat(salon), _etat(None))
    salon.delete.assert_awaited_once()
    assert db.ids == set()


async def test_salon_non_gere_vide_jamais_supprime():
    salon = _salon(888, membres=[])
    await st.sur_changement_vocal(_bot(FauxDb({777})), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    salon.delete.assert_not_awaited()


async def test_salon_gere_encore_occupe_garde():
    salon = _salon(777, membres=[object()])
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    salon.delete.assert_not_awaited()
    assert db.ids == {777}


async def test_salon_deja_supprime_retire_la_ligne():
    salon = _salon(777, membres=[])
    salon.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Channel"))
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(None))
    assert db.ids == set()


async def test_desactive_ne_fait_rien():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock())
    salon = _salon(777, membres=[])
    db = FauxDb({777})
    await st.sur_changement_vocal(_bot(db, createur=None), SimpleNamespace(id=1, bot=False),
                                  _etat(salon), _etat(_salon(CREATEUR, guild=guild)))
    guild.create_voice_channel.assert_not_awaited()
    salon.delete.assert_not_awaited()


async def test_menage_au_boot():
    vide, occupe = _salon(1, membres=[]), _salon(2, membres=[object()])
    db = FauxDb({1, 2, 3})           # 3 : salon disparu pendant l'arrêt
    bot = _bot(db)
    bot.salons = {1: vide, 2: occupe}
    await st.menage_au_boot(bot)
    vide.delete.assert_awaited_once()
    occupe.delete.assert_not_awaited()
    assert db.ids == {2}


async def test_menage_au_boot_une_panne_sur_un_salon_n_arrete_pas_les_autres():
    casse = _salon(1, membres=[])
    casse.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "interdit"))
    vide = _salon(2, membres=[])
    db = FauxDb({1, 2})
    bot = _bot(db)
    bot.salons = {1: casse, 2: vide}

    await st.menage_au_boot(bot)

    casse.delete.assert_awaited_once()
    vide.delete.assert_awaited_once()
    # Le salon en échec n'a pas pu être retiré du registre (l'exception
    # a coupé `_supprimer` avant l'écriture), l'autre si.
    assert db.ids == {1}


async def test_une_panne_ne_remonte_jamais():
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(side_effect=RuntimeError("boom")))
    db = FauxDb()
    await st.sur_changement_vocal(_bot(db), _Membre(id=1, bot=False, display_name="A"),
                                  _etat(None), _etat(_salon(CREATEUR, guild=guild)))
    # La panne doit avoir été atteinte (pas masquée plus tôt) et avalée.
    guild.create_voice_channel.assert_awaited_once()
    assert db.ids == set()


async def test_enregistrement_db_echoue_supprime_le_salon_cree():
    """`create_voice_channel` réussit mais `salon_temporaire_ajouter` casse :
    sans nettoyage, le salon existe côté Discord mais jamais dans le
    registre — orphelin pour toujours (ni `_supprimer_si_gere` ni
    `menage_au_boot` ne le verraient)."""
    nouveau = _salon(777)
    guild = SimpleNamespace(id=9, create_voice_channel=AsyncMock(return_value=nouveau))
    membre = _Membre(id=1, bot=False, move_to=AsyncMock(), display_name="A")

    class DbCasse(FauxDb):
        async def salon_temporaire_ajouter(self, channel_id, guild_id):
            raise RuntimeError("db hs")

    db = DbCasse()
    # La ligne n'a jamais été écrite : le nettoyage ne doit PAS rappeler la
    # base (une seconde panne y masquerait la cause réelle déjà journalisée).
    db.salon_temporaire_retirer = AsyncMock()
    await st.sur_changement_vocal(_bot(db), membre, _etat(None),
                                  _etat(_salon(CREATEUR, guild=guild)))
    nouveau.delete.assert_awaited_once()
    membre.move_to.assert_not_awaited()
    db.salon_temporaire_retirer.assert_not_awaited()


async def test_l_accueil_vocal_est_toujours_appele(monkeypatch):
    from bot.discord.bot import WallyDiscord

    appels = []

    async def faux_sur_changement(bot, member, before, after):
        appels.append("salons")

    monkeypatch.setattr(st, "sur_changement_vocal", faux_sur_changement)
    vs = SimpleNamespace(is_connected=True, channel_id=42, greet_newcomer=AsyncMock(),
                         members_in_channel=lambda: [object()])
    self = SimpleNamespace(voice_service=vs, user=SimpleNamespace(id=999))
    membre = SimpleNamespace(id=1, bot=False)
    await WallyDiscord.on_voice_state_update(self, membre, _etat(None), _etat(SimpleNamespace(id=42)))
    assert appels == ["salons"]
    vs.greet_newcomer.assert_awaited_once_with(membre)
