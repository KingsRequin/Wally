# tests/test_apex_client.py
"""Le client Apex : cache par endpoint, débit borné, erreurs non mémorisées."""
import pytest

from bot.core.apex.client import DEFAULT_TTL, ApexClient


def _client(responses, clock):
    """Un client dont le réseau est doublé et l'horloge injectée."""
    calls = []
    client = ApexClient(api_key="k", now=clock)

    async def _fetch(endpoint, params):
        calls.append((endpoint, params))
        return responses.pop(0) if len(responses) > 1 else responses[0]

    client._fetch = _fetch          # seul point réseau
    return client, calls


@pytest.mark.asyncio
async def test_deux_demandes_rapprochees_ne_font_qu_un_appel():
    t = [1000.0]
    client, calls = _client([{"map": "Olympus"}], lambda: t[0])
    a = await client.get("maprotation", {"version": "2"})
    t[0] += 10
    b = await client.get("maprotation", {"version": "2"})
    assert a == b == {"map": "Olympus"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_le_cache_expire_selon_l_endpoint():
    t = [1000.0]
    client, calls = _client([{"n": 1}, {"n": 2}], lambda: t[0])
    await client.get("maprotation")
    t[0] += DEFAULT_TTL["maprotation"] + 1
    assert await client.get("maprotation") == {"n": 2}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_des_parametres_differents_sont_des_entrees_distinctes():
    t = [1000.0]
    client, calls = _client([{"p": "a"}, {"p": "b"}], lambda: t[0])
    await client.get("bridge", {"player": "A"})
    await client.get("bridge", {"player": "B"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_une_erreur_n_est_jamais_mise_en_cache():
    """Sinon une panne d'une seconde condamne l'endpoint pour tout son TTL."""
    t = [1000.0]
    client = ApexClient(api_key="k", now=lambda: t[0])
    appels = []

    async def _fetch(endpoint, params):
        appels.append(endpoint)
        if len(appels) == 1:
            raise RuntimeError("réseau coupé")
        return {"ok": True}

    client._fetch = _fetch
    premier = await client.get("servers")
    assert isinstance(premier, str) and "error" in premier.lower()
    assert await client.get("servers") == {"ok": True}
    assert len(appels) == 2


def test_indisponible_sans_cle():
    assert ApexClient(api_key="").available is False
    assert ApexClient(api_key="k").available is True
