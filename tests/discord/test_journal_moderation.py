from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot.discord import journal_moderation as jm

LOGS, COMMU = 70, 9


def _bot(salon_id=LOGS, guild_ids=(COMMU,)):
    logs = SimpleNamespace(id=LOGS, send=AsyncMock())
    salons = {LOGS: logs, 5: SimpleNamespace(id=5, name="discussions")}
    cfg = SimpleNamespace(salon_id=salon_id, guild_ids=list(guild_ids))
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    return bot, logs


def _message(contenu, *, bot_auteur=False, guild=COMMU, pieces=()):
    return SimpleNamespace(
        id=1, content=contenu, guild=SimpleNamespace(id=guild),
        channel=SimpleNamespace(id=5, name="discussions"),
        author=SimpleNamespace(bot=bot_auteur, name="alice"),
        attachments=[SimpleNamespace(filename=p, url=f"u/{p}") for p in pieces],
    )


def _embed(logs):
    return logs.send.await_args.kwargs["embed"]


async def test_suppression_en_cache_journalisee_sans_mention():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1,
                              cached_message=_message("salut @everyone", pieces=["a.png"]))
    await jm.message_supprime(bot, payload)
    kwargs = logs.send.await_args.kwargs
    assert kwargs["allowed_mentions"].everyone is False
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert valeurs["Contenu"] == "salut @​everyone"
    assert "a.png" in valeurs["Pièces jointes (1)"]


async def test_suppression_hors_cache():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=COMMU, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert valeurs["Contenu"] == "[contenu non disponible]"
    assert valeurs["Auteur"] == "inconnu"


async def test_guild_hors_liste_ignoree():
    bot, logs = _bot()
    payload = SimpleNamespace(guild_id=123, channel_id=5, message_id=1, cached_message=None)
    await jm.message_supprime(bot, payload)
    logs.send.assert_not_awaited()


async def test_desactive():
    bot, logs = _bot(salon_id=None)
    await jm.message_supprime(bot, SimpleNamespace(guild_id=COMMU, channel_id=5,
                                                   message_id=1, cached_message=None))
    logs.send.assert_not_awaited()


async def test_contenu_tronque_a_1024():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a"), _message("b" * 3000))
    valeurs = {f.name: f.value for f in _embed(logs).fields}
    assert len(valeurs["Après"]) == 1024


async def test_edition_sans_changement_de_texte_ignoree():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("lien"), _message("lien"))
    logs.send.assert_not_awaited()


async def test_edition_par_un_bot_ignoree():
    bot, logs = _bot()
    await jm.message_modifie(bot, _message("a", bot_auteur=True), _message("b", bot_auteur=True))
    logs.send.assert_not_awaited()


async def test_vocal_cree_et_supprime():
    bot, logs = _bot()
    salon = SimpleNamespace(id=777, name="Arène", guild=SimpleNamespace(id=COMMU))
    await jm.vocal_cree(bot, SimpleNamespace(name="alice"), salon)
    await jm.vocal_supprime(bot, salon)
    assert logs.send.await_count == 2


async def test_salon_de_logs_injoignable_ne_leve_pas():
    bot, logs = _bot()
    logs.send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "Forbidden")
    await jm.message_modifie(bot, _message("a"), _message("b"))


async def test_edits_journalise_meme_dans_une_guild_ignoree(monkeypatch):
    """L'appel est posé AVANT le filtre `ignored_guilds` de la perception."""
    from bot.discord.events import edits

    appels = []

    async def faux(bot, before, after):
        appels.append(after.content)

    monkeypatch.setattr(jm, "message_modifie", faux)
    faux_bot = SimpleNamespace(user=SimpleNamespace(id=999),
                               config=SimpleNamespace(discord=SimpleNamespace(ignored_guilds={COMMU})))
    handlers = {}
    faux_bot.event = lambda f: handlers.setdefault(f.__name__, f)
    edits.register(faux_bot)
    await handlers["on_message_edit"](_message("a"), _message("b"))
    assert appels == ["b"]
