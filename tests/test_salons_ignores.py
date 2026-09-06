# tests/test_salons_ignores.py
"""Les salons Discord que Wally ignore — page « Discord › Salons ».

Ignorer un salon veut dire quatre choses à la fois : pas de réponse, pas de
réaction, pas de perception, pas de fait mémorisé. La liste qui le décide
(`discord.channel_blacklist`) était lue EN DERNIER et seulement en mode
`blacklist` : `per_guild_channel_whitelist` la neutralisait en silence, et les
sept salons exclus du Purgatoire étaient lus depuis toujours. Ces tests
tiennent la priorité, faute de quoi le bouton « Ignorer » du panneau
n'ignorerait rien sur les serveurs qui portent une whitelist.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bot.dashboard.routes.admin import _ids_de_salons, _salons_ignores, list_ignored
from bot.discord.handlers import _is_channel_allowed


def _config(*, blacklist=(), whitelist=(), mode="blacklist", pgw=None):
    return SimpleNamespace(discord=SimpleNamespace(
        channel_blacklist=list(blacklist),
        channel_whitelist=list(whitelist),
        channel_filter_mode=mode,
        per_guild_channel_whitelist=dict(pgw or {}),
    ))


# ── La priorité ─────────────────────────────────────────────────────────────

def test_un_salon_ignore_le_reste_malgre_la_whitelist_du_serveur():
    """Le cas vécu : `per_guild_channel_whitelist` du Purgatoire vaut `null`
    (« tous les salons »), et rendait la liste des ignorés inopérante."""
    cfg = _config(blacklist=[999], pgw={"1": None})
    assert _is_channel_allowed(cfg, 999, 1) is False
    assert _is_channel_allowed(cfg, 111, 1) is True


def test_un_salon_ignore_le_reste_malgre_une_whitelist_qui_le_liste():
    cfg = _config(blacklist=[999], pgw={"1": [999, 111]})
    assert _is_channel_allowed(cfg, 999, 1) is False
    assert _is_channel_allowed(cfg, 111, 1) is True


def test_un_salon_ignore_le_reste_en_mode_whitelist():
    """En mode `whitelist`, la liste des ignorés n'était pas lue du tout."""
    cfg = _config(blacklist=[999], whitelist=[999, 111], mode="whitelist")
    assert _is_channel_allowed(cfg, 999, 1) is False
    assert _is_channel_allowed(cfg, 111, 1) is True


def test_un_salon_ignore_le_reste_en_mode_none():
    cfg = _config(blacklist=[999], mode="none")
    assert _is_channel_allowed(cfg, 999, 1) is False


def test_les_dm_restent_autorises():
    cfg = _config(blacklist=[999])
    assert _is_channel_allowed(cfg, 999, None) is True


def test_always_trigger_ne_ressuscite_pas_un_salon_ignore():
    """`always_trigger_channels` dit « ici tout message s'adresse à Wally »,
    pas « ici, on passe outre la liste des ignorés »."""
    import inspect

    from bot.discord import handlers

    src = inspect.getsource(handlers.handle_message)
    debut = src.index("channel_allowed = _is_channel_allowed(")
    fin = src.index("_is_always_trigger = ")
    # Le calcul de `channel_allowed` vient AVANT, et ne dépend plus du trigger.
    assert debut < fin


# ── L'écriture : des chaînes qui redeviennent des entiers ───────────────────

def test_les_ids_du_navigateur_arrivent_en_chaines_et_ressortent_entiers():
    """Un snowflake ne survit pas à un `Number` JavaScript : le front envoie
    du texte. Rangé tel quel, il ne serait jamais égal à `channel.id`."""
    assert _ids_de_salons(["882793497663537172", 111], "channel_blacklist") == [
        882793497663537172, 111]


def test_un_id_illisible_est_refuse_plutot_qu_ignore():
    with pytest.raises(HTTPException) as e:
        _ids_de_salons(["général"], "channel_blacklist")
    assert e.value.status_code == 400


def test_une_valeur_qui_n_est_pas_une_liste_est_refusee():
    with pytest.raises(HTTPException):
        _ids_de_salons("999", "channel_blacklist")


# ── La lecture : ce que la page affiche ─────────────────────────────────────

def _state(*, blacklist=(), salons=None):
    """`salons` : id → (nom du salon, nom du serveur, id du serveur)."""
    table = dict(salons or {})

    def get_channel(cid):
        trouve = table.get(cid)
        if trouve is None:
            return None
        nom, serveur, gid = trouve
        return SimpleNamespace(name=nom, guild=SimpleNamespace(name=serveur, id=gid))

    return SimpleNamespace(
        config=SimpleNamespace(discord=SimpleNamespace(channel_blacklist=list(blacklist))),
        discord_bot=SimpleNamespace(get_channel=get_channel),
    )


def test_le_salon_porte_son_nom_et_celui_du_serveur():
    rendu = _salons_ignores(_state(
        blacklist=[999], salons={999: ("partie-privée", "Le Purgatoire", 875)}))
    assert rendu == [{"id": "999", "nom": "partie-privée",
                      "serveur": "Le Purgatoire", "serveur_id": "875"}]


def test_un_salon_invisible_garde_son_id_pour_rester_retirable():
    """Serveur quitté, salon supprimé, bot hors ligne : la carte doit rester,
    sinon le salon reste ignoré sans que personne ne puisse l'en sortir."""
    rendu = _salons_ignores(_state(blacklist=[999]))
    assert rendu == [{"id": "999", "nom": "", "serveur": "", "serveur_id": ""}]


def test_les_ids_partent_en_chaines():
    """882793497663537172 devient 882793497663537200 en `Number` JavaScript."""
    rendu = _salons_ignores(_state(blacklist=[882793497663537172]))
    assert rendu[0]["id"] == "882793497663537172"


@pytest.mark.asyncio
async def test_les_salons_arrivent_avec_le_reste_des_ignores():
    from bot.config import TwitchConfig

    state = _state(blacklist=[999], salons={999: ("tiktok", "Le Purgatoire", 875)})
    state.config.twitch = TwitchConfig(guest_channels=[], cooldown_seconds=10)
    state.db = SimpleNamespace(list_chat_bans=AsyncMock(return_value=[]))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(wally=state)))

    rendu = await list_ignored(request)
    assert rendu["salons"][0]["nom"] == "tiktok"
