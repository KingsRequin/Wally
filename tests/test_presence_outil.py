"""« Qui est en ligne ? » — l'information existait, le chemin de réponse ne l'avait pas.

`PresenceService` alimente `AttentionContext` depuis longtemps : la COGNITION
voyait les statuts Discord. Le chemin de RÉPONSE, lui, n'y avait pas accès, et
Wally répondait « je peux pas voir qui est en ligne, connecté, idle, tout ça »
alors qu'il recevait l'information à chaque tick.

Le piège spécifique ici est la TRONCATURE : `roster()` plafonne, et une absence
de la liste ne prouve rien si la liste est coupée. Sans le dire, Wally conclut
« il est pas là » d'un plafond.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from bot.discord.handlers import _PRESENCE_LIMITE, _presence_service, run_presence_tool


def _service(lignes, enabled=True):
    s = MagicMock()
    s.enabled = enabled
    s.roster.return_value = lignes
    return s


def _bot(lignes, **kw):
    return SimpleNamespace(presence=_service(lignes, **kw))


def test_rend_les_connectes():
    out = json.loads(run_presence_tool(
        _bot(["Azraël est en ligne, joue à Apex", "Kings ne veut pas être dérangé"]), {}))
    assert out["status"] == "ok"
    assert "Azraël" in out["message"] and "Kings" in out["message"]


def test_liste_complete_autorise_a_conclure_une_absence():
    out = json.loads(run_presence_tool(_bot(["Azraël est en ligne"]), {}))
    assert "liste COMPLÈTE" in out["message"]


def test_liste_pleine_interdit_de_conclure_une_absence():
    """Le vrai piège : au plafond, « il n'y est pas » ne veut plus rien dire."""
    out = json.loads(run_presence_tool(
        _bot([f"membre{i} est en ligne" for i in range(_PRESENCE_LIMITE)]), {}))
    assert "COUPÉE" in out["message"]
    assert "ne conclus pas" in out["message"]


def test_le_plafond_demande_est_bien_celui_qu_on_annonce():
    """Si `roster` était appelé avec son défaut (8), la détection de troncature
    porterait sur un autre nombre que celui reçu — et mentirait."""
    bot = _bot([])
    run_presence_tool(bot, {})
    assert bot.presence.roster.call_args.kwargs["limit"] == _PRESENCE_LIMITE


def test_personne_en_ligne():
    out = json.loads(run_presence_tool(_bot([]), {}))
    assert out["status"] == "nothing"
    assert "Ne nomme personne" in out["message"]


def test_service_desactive():
    out = json.loads(run_presence_tool(_bot(["x"], enabled=False), {}))
    assert out["status"] == "unavailable"


def test_sans_service_du_tout():
    out = json.loads(run_presence_tool(SimpleNamespace(), {}))
    assert out["status"] == "unavailable"


def test_le_service_est_atteint_depuis_les_deux_plateformes():
    """`WallyTwitch` ne l'a que par `discord_bot`, comme `voice_service`."""
    s = _service([])
    assert _presence_service(SimpleNamespace(presence=s)) is s
    assert _presence_service(SimpleNamespace(discord_bot=SimpleNamespace(presence=s))) is s
    assert _presence_service(SimpleNamespace()) is None


async def test_offert_des_deux_cotes():
    from bot.discord.handlers import build_chat_tools as outils_discord
    from bot.twitch.handlers import build_chat_tools as outils_twitch

    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        presence=_service([]),
    )
    d = {t["function"]["name"] for t in await outils_discord(nu, author_id="42")}
    t = {t["function"]["name"] for t in await outils_twitch(nu, overlay=True)}
    assert "who_is_online" in d and "who_is_online" in t


async def test_offert_meme_depuis_une_chaine_invitee():
    """Lecture seule sur le Discord : rien d'engageant, comme le planning."""
    from bot.twitch.handlers import build_chat_tools as outils_twitch

    nu = SimpleNamespace(
        config=SimpleNamespace(bot=SimpleNamespace(owner_discord_id="1")),
        presence=_service([]),
    )
    noms = {t["function"]["name"] for t in await outils_twitch(nu, overlay=False)}
    assert "who_is_online" in noms


async def test_les_deux_executeurs_le_routent():
    """Au catalogue mais absent de `_impl` = un outil mort."""
    from bot.twitch.handlers import make_tool_executor

    ex = make_tool_executor(SimpleNamespace(), platform="twitch", user_id="1",
                            author="a", channel="c")
    out = json.loads(await ex("who_is_online", "{}"))
    assert out["status"] == "unavailable"
