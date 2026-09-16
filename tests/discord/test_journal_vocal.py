from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.db.database import Database
from bot.discord import journal_vocal as jv

LOGS, LOGS2, COMMU = 70, 71, 9
CREATEUR = 500


def _salon_log(sid, *, edit_side_effect=None, message_id=None):
    salon = SimpleNamespace(id=sid)
    salon.send = AsyncMock(return_value=SimpleNamespace(id=message_id or (1000 + sid)))
    partial = SimpleNamespace(edit=AsyncMock(side_effect=edit_side_effect))
    salon.get_partial_message = MagicMock(return_value=partial)
    salon._partial = partial
    return salon


def _bot(db, *, salon_ids=(LOGS,), guild_ids=(COMMU,), createur=None):
    salons = {sid: _salon_log(sid) for sid in salon_ids}
    cfg_journal = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids), inclure_bots=False)
    cfg_temp = SimpleNamespace(salon_createur_id=createur, noms=[])
    bot = SimpleNamespace(db=db, config=SimpleNamespace(
        discord=SimpleNamespace(journal_moderation=cfg_journal, salons_temporaires=cfg_temp)))
    bot.get_channel = lambda cid: salons.get(cid)
    return bot, salons


def _textes(vue) -> list[str]:
    return [c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay)]


def _vue_envoyee(salon, appel=0):
    return salon.send.await_args_list[appel].kwargs["view"]


def _vue_editee(salon):
    return salon._partial.edit.await_args.kwargs["view"]


def _canal(cid, guild=None):
    return SimpleNamespace(id=cid, mention=f"<#{cid}>", guild=guild or SimpleNamespace(id=COMMU))


def _etat(channel):
    return SimpleNamespace(channel=channel)


async def _db(tmp_path, nom="t.db"):
    return await Database.create(str(tmp_path / nom))


# ---------------------------------------------------------------------------
# vocal_cree


async def test_vocal_cree_publie_une_carte_et_range_en_base(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        membre = SimpleNamespace(id=42, name="alice")

        await jv.vocal_cree(bot, membre, salon)

        texte = "\n".join(_textes(_vue_envoyee(salons[LOGS])))
        assert "<@42>" in texte
        assert "Arène" in texte
        assert re.search(r"<t:\d+:f> \(<t:\d+:R>\)", texte)
        assert "-# ID `42`" in texte

        cartes = await db.cartes_vocales(777)
        assert len(cartes) == 1
        assert cartes[0]["createur_id"] == 42
        assert cartes[0]["participants"] == [42]
        assert cartes[0]["message_id"] == salons[LOGS].send.return_value.id
    finally:
        await db.close()


async def test_vocal_cree_une_carte_par_salon_de_logs(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db, salon_ids=(LOGS, LOGS2))
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)

        assert salons[LOGS].send.await_count == 1
        assert salons[LOGS2].send.await_count == 1
        cartes = await db.cartes_vocales(777)
        assert {c["log_salon_id"] for c in cartes} == {LOGS, LOGS2}
    finally:
        await db.close()


async def test_vocal_cree_desactive_rien_publie_rien_range(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db, salon_ids=())
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
        assert await db.cartes_vocales(777) == []
    finally:
        await db.close()


async def test_vocal_cree_sans_guild_ne_leve_pas(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, _salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène")  # pas de `.guild`
        await jv.vocal_cree(bot, SimpleNamespace(id=1, name="alice"), salon)
    finally:
        await db.close()


async def test_vocal_cree_salon_de_logs_en_echec_n_empeche_pas_les_autres(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db, salon_ids=(LOGS, LOGS2))
        salons[LOGS].send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "boom")
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
        cartes = await db.cartes_vocales(777)
        assert {c["log_salon_id"] for c in cartes} == {LOGS2}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# vocal_supprime — édition, durée, participants


async def test_vocal_supprime_edite_la_carte_avec_duree_et_participants(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        createur = SimpleNamespace(id=42, name="alice")
        await jv.vocal_cree(bot, createur, salon)
        await db.carte_vocale_participant_ajouter(777, 1)
        await db.carte_vocale_participant_ajouter(777, 2)

        await jv.vocal_supprime(bot, salon)

        salons[LOGS]._partial.edit.assert_awaited_once()
        texte = "\n".join(_textes(_vue_editee(salons[LOGS])))
        assert "Arène" in texte
        assert "<@42>" in texte     # créateur
        assert "<@1>" in texte and "<@2>" in texte   # participants ajoutés en cours de vie
        assert re.search(r"A vécu\*\* \d+ ?(s|min|h)", texte)
        # les deux horodatages (créé, supprimé) natifs Discord
        assert len(re.findall(r"<t:\d+:f> \(<t:\d+:R>\)", texte)) == 2

        assert await db.cartes_vocales(777) == []   # ligne retirée après édition
    finally:
        await db.close()


async def test_vocal_supprime_sans_carte_en_base_ne_publie_rien(tmp_path):
    """Création jamais journalisée (journal désactivé à l'époque) : rien à éditer."""
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_supprime(bot, salon)
        salons[LOGS].send.assert_not_awaited()
        salons[LOGS]._partial.edit.assert_not_awaited()
    finally:
        await db.close()


async def test_vocal_supprime_sans_guild_ne_leve_pas(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, _salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène")  # pas de `.guild`
        await jv.vocal_supprime(bot, salon)
    finally:
        await db.close()


async def test_carte_introuvable_republie_une_nouvelle_carte(tmp_path):
    """Message édité à la main / supprimé du salon de logs : `edit()` lève
    `NotFound`, une carte neuve part à la place — l'information ne se perd pas."""
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
        salons[LOGS]._partial.edit.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason="x"), "Unknown Message")

        await jv.vocal_supprime(bot, salon)

        assert salons[LOGS].send.await_count == 2   # création + carte neuve de remplacement
        texte = "\n".join(_textes(_vue_envoyee(salons[LOGS], appel=1)))
        assert "Arène" in texte
        assert await db.cartes_vocales(777) == []
    finally:
        await db.close()


async def test_salon_de_logs_introuvable_avertit_et_retire_quand_meme_la_ligne(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon)
        bot.get_channel = lambda cid: None   # le salon de logs a disparu depuis la création

        dits: list[str] = []
        jeton = jv.logger.add(lambda m: dits.append(str(m)), level="WARNING")
        try:
            await jv.vocal_supprime(bot, salon)
        finally:
            jv.logger.remove(jeton)

        assert any("introuvable" in d for d in dits)
        assert await db.cartes_vocales(777) == []
    finally:
        await db.close()


async def test_reboot_les_cartes_sont_relues_en_base(tmp_path):
    """Aucun état en RAM : une seconde `Database` sur le MÊME fichier (un
    process qui redémarre) retrouve les cartes et peut les éditer."""
    path = str(tmp_path / "vocal.db")
    db1 = await Database.create(path)
    try:
        bot1, _salons1 = _bot(db1)
        salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot1, SimpleNamespace(id=42, name="alice"), salon)
    finally:
        await db1.close()

    db2 = await Database.create(path)   # nouvelle connexion, nouveau process simulé
    try:
        bot2, salons2 = _bot(db2)
        await jv.vocal_supprime(bot2, salon)
        salons2[LOGS]._partial.edit.assert_awaited_once()
        texte = "\n".join(_textes(_vue_editee(salons2[LOGS])))
        assert "<@42>" in texte
        assert await db2.cartes_vocales(777) == []
    finally:
        await db2.close()


# ---------------------------------------------------------------------------
# mouvement_vocal


async def test_mouvement_entree_publie_une_fiche(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = _canal(1)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(None), _etat(salon))

        texte = "\n".join(_textes(_vue_envoyee(salons[LOGS])))
        assert "Entrée" in texte
        assert "<@1>" in texte and "<#1>" in texte
        assert re.search(r"<t:\d+:f> \(<t:\d+:R>\)", texte)
    finally:
        await db.close()


async def test_mouvement_sortie_publie_une_fiche(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = _canal(1)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(salon), _etat(None))

        texte = "\n".join(_textes(_vue_envoyee(salons[LOGS])))
        assert "Sortie" in texte
        assert "<@1>" in texte and "<#1>" in texte
    finally:
        await db.close()


async def test_mouvement_deplacement_avant_vers_apres(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        avant, apres = _canal(1), _canal(2)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(avant), _etat(apres))

        texte = "\n".join(_textes(_vue_envoyee(salons[LOGS])))
        assert "Déplacement" in texte
        assert "**De** <#1>" in texte
        assert "**Vers** <#2>" in texte
    finally:
        await db.close()


async def test_mouvement_mute_sourdine_meme_salon_ignore(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon = _canal(1)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(salon), _etat(salon))

        salons[LOGS].send.assert_not_awaited()
    finally:
        await db.close()


async def test_mouvement_bot_ignore(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        membre = SimpleNamespace(id=1, bot=True)

        await jv.mouvement_vocal(bot, membre, _etat(None), _etat(_canal(1)))

        salons[LOGS].send.assert_not_awaited()
    finally:
        await db.close()


async def test_mouvement_salon_createur_ignore_a_l_entree(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db, createur=CREATEUR)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(None), _etat(_canal(CREATEUR)))

        salons[LOGS].send.assert_not_awaited()
    finally:
        await db.close()


async def test_mouvement_salon_createur_ignore_au_depart_vers_le_temporaire(tmp_path):
    """L'aller-retour créateur → salon perso créé à la volée : la carte vocale
    (`vocal_cree`) le couvre déjà, republier serait du bruit."""
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db, createur=CREATEUR)
        membre = SimpleNamespace(id=1, bot=False)

        await jv.mouvement_vocal(bot, membre, _etat(_canal(CREATEUR)), _etat(_canal(777)))

        salons[LOGS].send.assert_not_awaited()
    finally:
        await db.close()


async def test_mouvement_desactive_ne_publie_rien(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, _salons = _bot(db, salon_ids=())
        membre = SimpleNamespace(id=1, bot=False)
        await jv.mouvement_vocal(bot, membre, _etat(None), _etat(_canal(1)))   # ne lève pas
    finally:
        await db.close()


async def test_mouvement_entree_dans_un_salon_temporaire_ajoute_le_participant(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, salons = _bot(db)
        salon_temp = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
        await jv.vocal_cree(bot, SimpleNamespace(id=42, name="alice"), salon_temp)

        arrivant = SimpleNamespace(id=99, bot=False)
        canal_temp = _canal(777)
        await jv.mouvement_vocal(bot, arrivant, _etat(None), _etat(canal_temp))

        cartes = await db.cartes_vocales(777)
        assert set(cartes[0]["participants"]) == {42, 99}
    finally:
        await db.close()


async def test_mouvement_entree_dans_un_salon_ordinaire_n_ajoute_aucun_participant(tmp_path):
    db = await _db(tmp_path)
    try:
        bot, _salons = _bot(db)
        membre = SimpleNamespace(id=1, bot=False)
        await jv.mouvement_vocal(bot, membre, _etat(None), _etat(_canal(1)))
        assert await db.cartes_vocales(1) == []
    finally:
        await db.close()
