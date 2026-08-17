"""Quand la chaîne est pleine, le message doit dire la VRAIE raison.

Vécu le 2026-08-17 : le bot annonçait « PLAFOND de 50 récompenses », l'owner
comptait 33 dans son tableau de bord et concluait à une panne du bot. Les deux
chiffres étaient justes : Twitch compte les récompenses **désactivées** dans les
50 (doc officielle : « includes both enabled and disabled rewards »), et le
tableau de bord ne les montre pas dans sa vue par défaut. Sur la chaîne : 50
récompenses dont **19 désactivées**, invisibles.

Un chiffre asséné sans sa mesure se fait contredire par un autre chiffre. Le
message porte donc l'inventaire réel, et le geste qui libère vraiment une place
(supprimer — désactiver n'en libère aucune).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger as _loguru


def _resp(status, payload, texte=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = texte if texte is not None else str(payload)
    return r


def _api_avec(post_resp, get_resp):
    """Un POST de création qui échoue, un GET d'inventaire qui répond."""
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bot123", broadcaster_id="123")
    client = MagicMock()
    client.post = AsyncMock(return_value=post_resp)
    client.get = AsyncMock(return_value=get_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


_PLEIN = _resp(
    400,
    {"error": "Bad Request", "status": 400,
     "message": "CREATE_CUSTOM_REWARD_TOO_MANY_REWARDS"},
    texte='{"message":"CREATE_CUSTOM_REWARD_TOO_MANY_REWARDS"}',
)


def _inventaire(actives: int, eteintes: int):
    return _resp(200, {"data": [{"id": f"a{i}", "is_enabled": True} for i in range(actives)]
                               + [{"id": f"e{i}", "is_enabled": False} for i in range(eteintes)]})


async def _creer_en_capturant(monkeypatch, post_resp, get_resp) -> list[str]:
    api, client = _api_avec(post_resp, get_resp)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    lignes: list[str] = []
    jeton = _loguru.add(lambda m: lignes.append(str(m)), level="ERROR")
    try:
        assert await api.creer_recompense("Avalanche de memes", 50000, "p") is None
    finally:
        _loguru.remove(jeton)
    return lignes


@pytest.mark.asyncio
async def test_le_message_compte_les_desactivees(monkeypatch):
    """Le cas réel : 31 visibles, 19 éteintes, 50 au total."""
    lignes = await _creer_en_capturant(monkeypatch, _PLEIN, _inventaire(31, 19))
    plafond = " ".join(lignes)
    assert "50" in plafond
    assert "19" in plafond, plafond
    assert "désactiv" in plafond.lower(), plafond


@pytest.mark.asyncio
async def test_le_message_dit_de_SUPPRIMER_pas_de_desactiver(monkeypatch):
    """Désactiver ne libère aucune place — c'est le contresens que le message
    doit couper court."""
    lignes = await _creer_en_capturant(monkeypatch, _PLEIN, _inventaire(31, 19))
    plafond = " ".join(lignes).lower()
    assert "supprim" in plafond, plafond


@pytest.mark.asyncio
async def test_l_inventaire_compte_TOUTE_la_chaine_pas_seulement_les_notres(monkeypatch):
    """`only_manageable_rewards=true` ne rendrait que la nôtre (une seule) et
    ferait mentir le décompte du plafond, qui est par CHAÎNE."""
    api, client = _api_avec(_PLEIN, _inventaire(31, 19))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("Avalanche de memes", 50000, "p")
    params = client.get.call_args.kwargs["params"]
    assert params.get("only_manageable_rewards") in (None, "false")


@pytest.mark.asyncio
async def test_un_inventaire_indisponible_ne_fait_pas_taire_le_diagnostic(monkeypatch):
    """Le GET peut échouer ; la cause reste connue et doit être dite quand même
    — sans inventer de chiffres."""
    lignes = await _creer_en_capturant(monkeypatch, _PLEIN, _resp(500, {"message": "boom"}))
    plafond = " ".join(lignes).lower()
    assert "plafond" in plafond, plafond
    assert "supprim" in plafond, plafond


@pytest.mark.asyncio
async def test_une_autre_erreur_ne_devient_pas_un_plafond(monkeypatch):
    """Le 403 « not a partner or affiliate » a le même code HTTP de famille :
    il ne doit pas hériter du discours sur le plafond."""
    lignes = await _creer_en_capturant(
        monkeypatch, _resp(403, {"message": "The broadcaster is not a partner"}),
        _inventaire(31, 19))
    assert not any("plafond" in l.lower() for l in lignes), lignes
