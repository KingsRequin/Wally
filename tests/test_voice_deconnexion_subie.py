"""Être déconnecté n'est pas partir : Wally doit revenir.

Vécu le 2026-08-08 pendant le live : à 22:36:32 la connexion réseau lâche
(`no close frame received`, session STT perdue, EventSub vidé dans la même
seconde). Discord signale la sortie du salon, le bot appelle `leave()` — et
`leave()` pose `listen_optout = True` en supposant que la sortie est voulue.

Le veilleur de `main.py` (`if vs.is_connected or vs.listen_optout: continue`)
cesse alors de le ramener, jusqu'à la FIN du live. Wally est resté absent 21
minutes d'un live en cours, sans une ligne dans les logs pour l'expliquer :
le veilleur tournait toutes les 30 s et repartait en silence.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.test_voice_listen_only import _service


def _connected(svc):
    svc._vc = MagicMock()
    svc._vc.disconnect = AsyncMock()
    svc._channel = SimpleNamespace(id=42, name="stream")
    svc.listen_only = True
    svc.listen_optout = False
    return svc


@pytest.mark.asyncio
async def test_une_deconnexion_subie_ne_vaut_pas_un_conge():
    """Kick ou coupure réseau : il doit rester rattrapable par le veilleur."""
    svc = _connected(_service())

    await svc.leave(voluntary=False)

    assert svc.listen_optout is False


@pytest.mark.asyncio
async def test_un_depart_volontaire_reste_un_conge():
    """La régression à éviter : sans ça, le veilleur le ramènerait de force
    aussitôt après un auto-leave pour salon vide."""
    svc = _connected(_service())

    await svc.leave()

    assert svc.listen_optout is True


@pytest.mark.asyncio
async def test_le_conge_ne_concerne_que_lecoute_seule():
    """Une conversation qu'on termine n'a jamais posé de congé."""
    svc = _connected(_service())
    svc.listen_only = False

    await svc.leave()

    assert svc.listen_optout is False


@pytest.mark.asyncio
async def test_changer_de_salon_ne_pose_pas_de_conge():
    """`_join_locked` quitte le salon courant avant de rejoindre le suivant :
    ce n'est pas un départ, c'est un déplacement. En mode conversation, le congé
    posé au passage survivait et empêchait le retour en écoute ensuite."""
    svc = _connected(_service())
    svc.listen_only = True
    channel = SimpleNamespace(id=99, name="autre", connect=AsyncMock())

    await svc._join_locked(channel, None, listen_only=False)

    assert svc.listen_optout is False


@pytest.mark.asyncio
async def test_le_bot_deconnecte_par_discord_reste_rattrapable(monkeypatch):
    """Bout en bout : le handler Discord doit signaler une sortie SUBIE."""
    from bot.discord.bot import WallyDiscord

    svc = _connected(_service())
    svc.leave = AsyncMock()

    bot = WallyDiscord.__new__(WallyDiscord)
    bot.voice_service = svc
    bot._connection = MagicMock()
    me = SimpleNamespace(id=7)
    # `user` est une property de discord.py : monkeypatch la restaure en sortie,
    # sinon tous les tests suivants hériteraient de ce faux bot.
    monkeypatch.setattr(WallyDiscord, "user", property(lambda self: me), raising=False)

    member = SimpleNamespace(id=7, bot=True)
    before = SimpleNamespace(channel=SimpleNamespace(id=42))
    after = SimpleNamespace(channel=None)

    await WallyDiscord.on_voice_state_update(bot, member, before, after)

    svc.leave.assert_awaited_once()
    assert svc.leave.await_args.kwargs.get("voluntary") is False


@pytest.mark.asyncio
async def test_en_ecoute_seule_aucun_auto_leave_nest_arme():
    """Un live a des silences, et des moments où le salon se vide : partir tout
    seul y serait absurde. C'est aussi ce qui garantit qu'aucun congé ne peut
    être posé dans le dos du veilleur — `leave()` n'en pose que depuis un vocal
    d'écoute, et rien ne l'appelle automatiquement dans ce mode."""
    svc = _service()
    svc._vc = None
    channel = SimpleNamespace(id=42, name="stream", connect=AsyncMock())

    await svc._join_locked(channel, None, listen_only=True)

    assert svc._auto_leave_task is None


@pytest.mark.asyncio
async def test_en_conversation_lauto_leave_veille():
    """La régression à éviter : sans lui, Wally squatte un salon vide."""
    svc = _service()
    svc._vc = None
    channel = SimpleNamespace(id=42, name="salon", connect=AsyncMock())

    await svc._join_locked(channel, None, listen_only=False)

    assert svc._auto_leave_task is not None
    svc._auto_leave_task.cancel()
