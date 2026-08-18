"""Wally doit créer la récompense lui-même.

« The app used to create the reward is the only app that may update the
redemption » : une récompense créée depuis le site Twitch renvoie 403 à tout
remboursement. Et chaque refus du duel rembourse.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _api(reponse):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock(); tm.streamer_token = "tok"; tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bot123", broadcaster_id="123")
    client = MagicMock()
    client.post = AsyncMock(return_value=reponse)
    client.get = AsyncMock(return_value=reponse)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock(); r.status_code = status
    r.json.return_value = payload; r.text = str(payload)
    return r


@pytest.mark.asyncio
async def test_creation_rend_l_id(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"id": "RW42", "title": "Duel Apex"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.creer_recompense("Duel Apex", 5000, "Ton uid Apex") == "RW42"


@pytest.mark.asyncio
async def test_la_saisie_de_texte_est_OBLIGATOIRE(monkeypatch):
    """Le viewer colle son uid à l'achat — sans ça, tout duel commence par une
    conversation."""
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("Duel Apex", 5000, "Ton uid")
    corps = client.post.call_args.kwargs["json"]
    assert corps["is_user_input_required"] is True


@pytest.mark.asyncio
async def test_la_file_de_validation_n_est_JAMAIS_sautee(monkeypatch):
    """Une redemption qui saute la file est aussitôt FULFILLED, et seul un
    statut UNFULFILLED peut être mis à jour : plus aucun remboursement."""
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("Duel Apex", 5000, "Ton uid")
    corps = client.post.call_args.kwargs["json"]
    assert corps["should_redemptions_skip_request_queue"] is False


@pytest.mark.asyncio
async def test_le_titre_est_tronque_a_45_caracteres(monkeypatch):
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("x" * 200, 5000, "y" * 500)
    corps = client.post.call_args.kwargs["json"]
    assert len(corps["title"]) <= 45
    assert len(corps["prompt"]) <= 200


@pytest.mark.asyncio
async def test_echec_de_creation_rend_None(monkeypatch):
    api, client = _api(_resp(403, {"message": "Forbidden"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.creer_recompense("Duel", 100, "p") is None


@pytest.mark.asyncio
async def test_recompenses_gerables_ne_liste_QUE_les_notres(monkeypatch):
    """only_manageable_rewards=true : celles créées par notre client_id, donc
    celles qu'on pourra rembourser."""
    api, client = _api(_resp(200, {"data": [{"id": "A", "title": "Duel Apex"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    rewards = await api.recompenses_gerables()
    assert rewards == [{"id": "A", "title": "Duel Apex"}]
    assert client.get.call_args.kwargs["params"]["only_manageable_rewards"] == "true"


@pytest.mark.asyncio
async def test_recompenses_gerables_rend_liste_vide_si_vraiment_aucune(monkeypatch):
    api, client = _api(_resp(200, {"data": []}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.recompenses_gerables() == []


@pytest.mark.asyncio
async def test_recompenses_gerables_rend_None_sur_erreur_jamais_liste_vide(monkeypatch):
    """Un `[]` sur erreur était indiscernable d'une vraie liste vide :
    `DuelRunner.assurer_recompense()` en concluait « ma récompense a
    disparu » sur un simple hoquet Twitch, et en recréait une seconde —
    écrasant l'ID persisté et rendant l'ancienne irremboursable (403)."""
    api, client = _api(_resp(500, {"message": "Internal Server Error"}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    assert await api.recompenses_gerables() is None


# ── le champ de texte n'est PAS imposé ──────────────────────────────────────

@pytest.mark.asyncio
async def test_une_recompense_peut_se_passer_du_champ_de_TEXTE(monkeypatch):
    """`is_user_input_required` est OPTIONNEL côté Twitch (défaut `false`), et
    on peut évidemment créer une récompense sans champ de saisie — c'est ce que
    fait n'importe qui depuis le tableau de bord.

    Il était posé à `True` en dur ici, hérité du duel qui attend un uid : toute
    récompense héritait donc d'un champ inutile, et l'attaque de memes devait
    écrire « rien à écrire » dans son invite pour s'en excuser.
    """
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("Sans saisie", 100, "p", saisie_requise=False)
    assert client.post.call_args.kwargs["json"]["is_user_input_required"] is False


@pytest.mark.asyncio
async def test_le_champ_de_texte_reste_disponible_pour_qui_en_a_besoin(monkeypatch):
    """Le duel y attend un uid, « forcer une humeur » l'émotion voulue."""
    api, client = _api(_resp(200, {"data": [{"id": "RW42"}]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)
    await api.creer_recompense("Avec saisie", 100, "p", saisie_requise=True)
    assert client.post.call_args.kwargs["json"]["is_user_input_required"] is True
