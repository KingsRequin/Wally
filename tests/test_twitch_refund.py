"""Annuler une redemption REND les points au viewer (statut CANCELED).

Chaque refus du duel doit rembourser : un viewer qui a payé et ne voit rien
est le pire résultat possible.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bid", broadcaster_id="123")
    client = MagicMock()
    client.patch = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = str(payload)
    return r


@pytest.mark.asyncio
async def test_remboursement_reussi(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"status": "CANCELED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is True
    _, kwargs = client.patch.call_args
    assert kwargs["json"] == {"status": "CANCELED"}
    assert kwargs["params"]["reward_id"] == "rw"
    assert kwargs["params"]["id"] == "rd"


@pytest.mark.asyncio
async def test_un_200_qui_ne_dit_pas_CANCELED_est_un_echec(monkeypatch):
    """Sur Helix, un 200 ne prouve pas que l'ordre est passé — ce projet l'a
    déjà payé avec is_sent. On lit le CORPS."""
    api, client = _api(_resp(200, {"data": [{"status": "UNFULFILLED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_corps_vide_est_un_echec(monkeypatch):
    api, client = _api(_resp(200, {"data": []}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_erreur_http_ne_leve_pas(monkeypatch):
    api, client = _api(_resp(403, {"error": "Forbidden"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_reward_id_ou_redemption_id_vide_ne_fait_aucun_appel_reseau(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"status": "CANCELED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("", "rd") is False
    assert await api.refund_redemption("rw", "") is False
    client.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_corps_json_illisible_ne_leve_pas(monkeypatch):
    reponse = _resp(200, {})
    reponse.json.side_effect = ValueError("pas du JSON")
    api, client = _api(reponse)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False


@pytest.mark.asyncio
async def test_401_puis_refresh_reussi_puis_200_rend_true(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"status": "CANCELED"}]}))
    unauthorized = _resp(401, {"error": "Unauthorized"})
    ok = _resp(200, {"data": [{"status": "CANCELED"}]})
    client.patch = AsyncMock(side_effect=[unauthorized, ok])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is True
    assert client.patch.await_count == 2
    api._tm.refresh.assert_awaited_once_with("streamer")


@pytest.mark.asyncio
async def test_401_avec_refresh_en_echec_rend_false(monkeypatch):
    api, client = _api(_resp(401, {"error": "Unauthorized"}))
    api._tm.refresh = AsyncMock(return_value=False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.refund_redemption("rw", "rd") is False
    client.patch.assert_awaited_once()
    api._tm.refresh.assert_awaited_once_with("streamer")


# ── Retrouver les achats manqués pendant un arrêt du bot ────────────────────
# EventSub ne rejoue rien : cette liste est le seul moyen de les récupérer.
def _api_get(reponses):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bid", broadcaster_id="123")
    client = MagicMock()
    client.get = AsyncMock(side_effect=list(reponses))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _page(ids, curseur=""):
    corps = {"data": [{"id": i, "status": "UNFULFILLED"} for i in ids]}
    if curseur:
        corps["pagination"] = {"cursor": curseur}
    return _resp(200, corps)


@pytest.mark.asyncio
async def test_les_redemptions_en_attente_ne_portent_que_notre_recompense(monkeypatch):
    api, client = _api_get([_page(["RD1"])])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert [r["id"] for r in await api.redemptions_en_attente("RW")] == ["RD1"]

    params = client.get.call_args.kwargs["params"]
    assert params["reward_id"] == "RW"
    assert params["status"] == "UNFULFILLED"


@pytest.mark.asyncio
async def test_la_pagination_est_suivie_jusqu_au_bout(monkeypatch):
    """Un stream chargé peut en accumuler plus d'une page : s'arrêter à la
    première laisserait des viewers sans leurs points."""
    api, client = _api_get([_page(["RD1"], curseur="c1"), _page(["RD2"])])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert [r["id"] for r in await api.redemptions_en_attente("RW")] == ["RD1", "RD2"]
    assert client.get.await_args_list[1].kwargs["params"]["after"] == "c1"


@pytest.mark.asyncio
async def test_une_liste_vide_est_une_liste_vide(monkeypatch):
    api, client = _api_get([_page([])])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.redemptions_en_attente("RW") == []


@pytest.mark.asyncio
async def test_une_erreur_ne_se_confond_pas_avec_aucun_achat(monkeypatch):
    """`None` et non `[]` : les confondre ferait conclure « rien à rembourser »
    sur une simple panne, et les points ne reviendraient jamais."""
    api, client = _api_get([_resp(403, {"error": "Forbidden"})])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.redemptions_en_attente("RW") is None


@pytest.mark.asyncio
async def test_un_curseur_qui_ne_bouge_pas_ne_fait_pas_tourner_le_boot_en_rond(monkeypatch):
    api, client = _api_get([_page([f"RD{i}"], curseur="toujours") for i in range(50)])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    lues = await api.redemptions_en_attente("RW")

    assert client.get.await_count <= 20, "la pagination doit être bornée"
    assert lues, "et rendre ce qu'elle a lu, pas rien"


@pytest.mark.asyncio
async def test_sans_reward_id_aucun_appel_ne_part(monkeypatch):
    api, client = _api_get([_page(["RD1"])])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.redemptions_en_attente("") is None
    client.get.assert_not_awaited()
