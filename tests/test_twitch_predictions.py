"""Les prédictions Twitch : créer, résoudre, annuler (§13).

L'API officielle, pas le « pari de Wally » de l'overlay — ici les viewers misent
de vrais points de chaîne, et une résolution fautive les leur prend.

LE POINT BLOQUANT, vérifié avant d'écrire une ligne : le token du streamer ne
porte PAS `channel:manage:predictions`. Relevé sur `/oauth2/validate` le
2026-08-18 — il n'a que quatre scopes. Tout ce module rendra donc 401 tant
qu'Azraël n'aura pas refait son autorisation depuis le dashboard, et c'est
exactement le genre de panne qu'il faut NOMMER : sans message clair, on relit le
code du bot en cherchant un défaut qui n'existe pas (déjà payé sur le plafond des
récompenses).

Les bornes de l'API, qu'on ne devine pas : titre 45 caractères, 2 à 10 choix de
25 caractères, fenêtre de pari de 30 s à 30 min.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger as _loguru


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock()
    tm.streamer_token = "tok"
    tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bot123", broadcaster_id="123")
    client = MagicMock()
    client.post = AsyncMock(return_value=reponse)
    client.patch = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload=None, texte=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    r.text = texte if texte is not None else str(payload)
    return r


_OUVERTE = _resp(200, {"data": [{
    "id": "pred-1", "title": "Combien de kills ?", "status": "ACTIVE",
    "outcomes": [{"id": "o1", "title": "0-2"}, {"id": "o2", "title": "3+"}],
}]})


# ── créer ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_prediction_est_creee_avec_ses_choix(monkeypatch):
    api, client = _api(_OUVERTE)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    pred = await api.creer_prediction("Combien de kills ?", ["0-2", "3+"], 120)
    assert pred["id"] == "pred-1"
    # Les identifiants des choix DOIVENT remonter : c'est avec eux qu'on résout,
    # et les libellés ne suffisent pas (deux choix peuvent se ressembler).
    assert [o["id"] for o in pred["outcomes"]] == ["o1", "o2"]
    corps = client.post.call_args.kwargs["json"]
    assert [o["title"] for o in corps["outcomes"]] == ["0-2", "3+"]
    assert corps["prediction_window"] == 120


@pytest.mark.asyncio
async def test_les_bornes_de_l_API_sont_respectees(monkeypatch):
    """Titre 45, choix 25, fenêtre 30 s à 30 min. Dépasser fait rendre 400 à
    Twitch, sans que rien ne dise lequel des trois est en cause."""
    api, client = _api(_OUVERTE)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_prediction("t" * 200, ["c" * 200, "d" * 200], 99999)
    corps = client.post.call_args.kwargs["json"]
    assert len(corps["title"]) <= 45
    assert all(len(o["title"]) <= 25 for o in corps["outcomes"])
    assert 30 <= corps["prediction_window"] <= 1800


@pytest.mark.asyncio
async def test_moins_de_DEUX_choix_est_refuse_avant_l_appel(monkeypatch):
    """Twitch en exige deux. Partir quand même ne ferait qu'un 400 illisible."""
    api, client = _api(_OUVERTE)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.creer_prediction("Un pari", ["seul"], 120) is None
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_plus_de_DIX_choix_sont_ecretes(monkeypatch):
    api, client = _api(_OUVERTE)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_prediction("Un pari", [f"c{i}" for i in range(30)], 120)
    assert len(client.post.call_args.kwargs["json"]["outcomes"]) <= 10


# ── le scope manquant, dit clairement ───────────────────────────────────────

@pytest.mark.asyncio
async def test_le_scope_MANQUANT_est_nomme_au_lieu_d_un_401_brut(monkeypatch):
    """Le défaut le plus coûteux serait un « 401 » sec dans les logs : on relit
    le bot en cherchant une panne qui n'existe pas. Le message doit dire QUOI
    faire — refaire l'autorisation du streamer depuis le dashboard.

    Même leçon que le plafond des récompenses de points de chaîne, où le code
    brut de Twitch ne disait ni le chiffre ni le geste.
    """
    api, client = _api(_resp(401, {"message": "Missing scope"},
                             texte='{"message":"Missing scope: channel:manage:predictions"}'))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    lignes: list[str] = []
    jeton = _loguru.add(lambda m: lignes.append(str(m)), level="ERROR")
    try:
        assert await api.creer_prediction("Un pari", ["a", "b"], 120) is None
    finally:
        _loguru.remove(jeton)
    dit = " ".join(lignes).lower()
    assert "autoris" in dit                      # le geste
    assert "channel:manage:predictions" in dit   # ce qui manque


# ── résoudre et annuler ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resoudre_designe_le_choix_gagnant(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"id": "pred-1", "status": "RESOLVED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.resoudre_prediction("pred-1", "o2") is True
    corps = client.patch.call_args.kwargs["json"]
    assert corps["status"] == "RESOLVED"
    assert corps["winning_outcome_id"] == "o2"


@pytest.mark.asyncio
async def test_annuler_REMBOURSE_les_paries(monkeypatch):
    """`CANCELED` rend leurs points à tout le monde. C'est la seule issue
    honnête quand le résultat n'est pas mesurable — résoudre au hasard
    punirait des gens qui avaient raison."""
    api, client = _api(_resp(200, {"data": [{"id": "pred-1", "status": "CANCELED"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.annuler_prediction("pred-1") is True
    assert client.patch.call_args.kwargs["json"]["status"] == "CANCELED"


@pytest.mark.asyncio
async def test_une_resolution_refusee_rend_FAUX(monkeypatch):
    """Et surtout pas True : l'appelant annoncerait un verdict qui n'a pas eu
    lieu, alors que les points sont toujours en jeu."""
    api, client = _api(_resp(400, {"message": "prediction is not active"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.resoudre_prediction("pred-1", "o2") is False


# ── le scope est demandé à l'autorisation ───────────────────────────────────

def test_le_scope_est_AJOUTE_sans_perdre_les_autres():
    """Un token fraîchement émis remplace l'ancien avec EXACTEMENT ce qu'on lui
    demande : n'en demander qu'un ferait perdre les abonnés, les bits et les
    récompenses sans un mot dans les logs. Le dépôt s'était déjà fait avoir.
    """
    from bot.dashboard.routes.twitch_auth import _STREAMER_SCOPES

    demandes = set(_STREAMER_SCOPES.split())
    assert "channel:manage:predictions" in demandes
    assert {"channel:read:subscriptions", "bits:read",
            "channel:read:redemptions", "channel:manage:redemptions"} <= demandes
