# tests/test_dashboard_ignores.py
"""L'inventaire de ce que Wally ignore, servi en un seul appel.

Trois mécanismes coexistent et ne se voient nulle part ensemble : la liste
Twitch de la config, la table des bannis Discord, et deux socles CÂBLÉS EN DUR
(les bots Discord, les bots Twitch connus). Sans un endroit qui les montre tous,
on ajoute « nightbot » à la main en se demandant pourquoi rien ne change.

Le socle est SERVI par cette route, jamais recopié dans le JavaScript : une
liste dupliquée au front diverge du jour où quelqu'un ajoute un bot au module
Python, et le panneau annonce alors le contraire du code qui décide.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.config import TwitchConfig
from bot.dashboard.routes.admin import list_ignored


def _request(*, ignores_twitch=None, bans=None):
    cfg = SimpleNamespace(
        twitch=TwitchConfig(guest_channels=[], cooldown_seconds=10,
                            ignored_users=list(ignores_twitch or [])),
        save=lambda: None,
    )
    db = SimpleNamespace(list_chat_bans=AsyncMock(return_value=list(bans or [])))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        wally=SimpleNamespace(config=cfg, db=db))))


@pytest.mark.asyncio
async def test_les_deux_listes_reglables_arrivent_ensemble():
    rendu = await list_ignored(_request(
        ignores_twitch=["wzbot"],
        bans=[{"discord_id": "42", "username": "MusicBot",
               "reason": None, "banned_at": 1_700_000_000}],
    ))
    assert rendu["twitch"] == ["wzbot"]
    assert rendu["discord"] == [{"id": "42", "label": "MusicBot",
                                 "reason": None, "depuis": 1_700_000_000}]


@pytest.mark.asyncio
async def test_le_socle_en_dur_est_servi_et_non_recopie_au_front():
    """LE point de la route. Un socle recopié en JS diverge en silence."""
    from bot.twitch.handlers import _KNOWN_BOTS

    socle = (await list_ignored(_request()))["socle"]
    assert sorted(socle["twitch"]) == sorted(_KNOWN_BOTS)
    assert socle["discord"]          # la phrase qui dit que tous les bots le sont


@pytest.mark.asyncio
async def test_un_banni_sans_pseudo_se_rabat_sur_son_id():
    """La table n'exige pas de pseudo : sans repli, la carte serait vide et on
    ne saurait plus qui on a ignoré."""
    rendu = await list_ignored(_request(bans=[{"discord_id": "77"}]))
    assert rendu["discord"][0]["label"] == "77"
    assert rendu["discord"][0]["depuis"] is None


@pytest.mark.asyncio
async def test_une_config_sans_liste_ne_casse_pas_la_route():
    """`ignored_users` a un défaut, mais un `config.yaml` antérieur peut porter
    `ignored_users: null` — et `.get(clé, défaut)` ne couvre PAS ce cas."""
    req = _request()
    req.app.state.wally.config.twitch.ignored_users = None
    assert (await list_ignored(req))["twitch"] == []
