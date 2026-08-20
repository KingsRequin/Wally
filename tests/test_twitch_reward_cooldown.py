# tests/test_twitch_reward_cooldown.py
"""Le temps de recharge d'une récompense de points de chaîne (2026-08-20).

Demandé pour l'attaque de meme : 50 000 points, mais deux achats coup sur coup
enchaînaient deux fois le même spectacle. Twitch sait le faire lui-même
(`is_global_cooldown_enabled` / `global_cooldown_seconds`) — c'est LUI qui
refuse l'achat, donc il n'y a rien à rembourser, et le chat voit le compte à
rebours sur le bouton.

Le piège de ce champ est son ASYMÉTRIE, confirmée dans la doc Twitch : la
requête le lit À PLAT, la réponse le rend IMBRIQUÉ dans
`global_cooldown_setting`. Sans aplatissement, la comparaison d'écarts ne
trouve jamais la clé et le cooldown n'est JAMAIS posé sur une récompense déjà
créée — précisément le cas d'Azraël, dont l'attaque de meme existe depuis des
jours.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

TITRE = "Attaque de meme"
PROMPT = "L'écran se fait submerger."
COUT = 50000
RECHARGE = 300


def _api(reponse, methode="patch"):
    from bot.twitch.api import TwitchAPI
    tm = MagicMock(); tm.streamer_token = "tok"; tm.refresh = AsyncMock(return_value=True)
    api = TwitchAPI(tm, client_id="cid", bot_id="bot123", broadcaster_id="123")
    client = MagicMock()
    setattr(client, methode, AsyncMock(return_value=reponse))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return api, client


def _resp(status, payload):
    r = MagicMock(); r.status_code = status
    r.json.return_value = payload; r.text = str(payload)
    return r


def _rendue(secondes):
    return {"id": "RW1", "title": TITRE, "cost": COUT, "prompt": PROMPT,
            "global_cooldown_setting": {"is_enabled": bool(secondes),
                                        "global_cooldown_seconds": secondes}}


@pytest.mark.asyncio
async def test_la_creation_pose_le_temps_de_recharge(monkeypatch):
    api, client = _api(_resp(200, {"data": [_rendue(RECHARGE)]}), methode="post")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.creer_recompense(TITRE, COUT, PROMPT, cooldown_s=RECHARGE) == "RW1"

    envoye = client.post.call_args.kwargs["json"]
    assert envoye["is_global_cooldown_enabled"] is True
    assert envoye["global_cooldown_seconds"] == RECHARGE


@pytest.mark.asyncio
async def test_sans_recharge_aucune_duree_n_est_envoyee(monkeypatch):
    """Twitch refuse 0 seconde ; « désactivé » se dit par le seul booléen."""
    api, client = _api(_resp(200, {"data": [_rendue(0)]}), methode="post")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    await api.creer_recompense(TITRE, COUT, PROMPT)

    envoye = client.post.call_args.kwargs["json"]
    assert envoye["is_global_cooldown_enabled"] is False
    assert "global_cooldown_seconds" not in envoye


@pytest.mark.asyncio
async def test_une_recompense_deja_creee_recoit_la_recharge(monkeypatch):
    """LE cas d'Azraël : la récompense existe, il faut la lui poser."""
    api, client = _api(_resp(200, {"data": [_rendue(RECHARGE)]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT,
                                    actuelle=_rendue(0), saisie_requise=False,
                                    cooldown_s=RECHARGE) is True

    envoye = client.patch.call_args.kwargs["json"]
    assert envoye["is_global_cooldown_enabled"] is True
    assert envoye["global_cooldown_seconds"] == RECHARGE


@pytest.mark.asyncio
async def test_une_recharge_deja_bonne_ne_patche_pas_a_chaque_boot(monkeypatch):
    """Sans aplatir la réponse, ce test passerait pour la mauvaise raison —
    d'où le précédent, qui exige que l'écart soit VU."""
    api, client = _api(_resp(200, {"data": [_rendue(RECHARGE)]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT,
                                    actuelle=_rendue(RECHARGE),
                                    saisie_requise=False,
                                    cooldown_s=RECHARGE) is True

    client.patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_la_verification_du_patch_lit_la_forme_imbriquee(monkeypatch):
    """Twitch REND le cooldown imbriqué : le relire à plat le croirait absent…
    ou pire, présent et différent, donc « non appliqué » sur un PATCH réussi."""
    api, client = _api(_resp(200, {"data": [_rendue(RECHARGE)]}))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: client)

    assert await api.maj_recompense("RW1", TITRE, COUT, PROMPT,
                                    actuelle=_rendue(0), saisie_requise=False,
                                    cooldown_s=RECHARGE) is True


@pytest.mark.asyncio
async def test_assurer_recompense_transmet_la_recharge():
    """Le paramètre traverse : sans ça, le réglage n'atteint jamais l'API."""
    from bot.twitch.recompenses import assurer_recompense

    api = MagicMock()
    api.recompenses_gerables = AsyncMock(return_value=[{"id": "RW1"}])
    api.maj_recompense = AsyncMock(return_value=True)
    db = MagicMock()
    db.get_state = AsyncMock(return_value="RW1")

    await assurer_recompense(api, db, cle_etat="k", titre=TITRE, cout=COUT,
                             prompt=PROMPT, cooldown_s=RECHARGE)

    assert api.maj_recompense.call_args.kwargs["cooldown_s"] == RECHARGE


@pytest.mark.asyncio
async def test_l_attaque_de_meme_a_cinq_minutes_de_recharge():
    """La valeur demandée par l'owner, lue là où elle est déclarée."""
    from bot.twitch.events.virus_popups import RECHARGE_S

    assert RECHARGE_S == 300
