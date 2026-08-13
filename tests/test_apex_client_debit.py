# tests/test_apex_client_debit.py
"""Le client doit exploiter le débit réellement autorisé, et savoir l'ignorer.

Mesuré le 2026-08-13 : l'API accepte 5 req/s (la limite n'est écrite que dans le
corps du 429). Le client en annonçait 2 et bridait d'autant — 60 % du débit payé
inutilisé, pour tout le projet.
"""
import pytest

from bot.core.apex.client import ApexClient, _MIN_INTERVAL


def test_intervalle_minimal_respecte_les_5_req_par_seconde():
    # 5 req/s => au plus 0,2 s entre deux requêtes.
    assert _MIN_INTERVAL <= 0.2


@pytest.mark.asyncio
async def test_sans_cache_refait_l_appel_reseau():
    """Le TTL de `bridge` est de 15 s : une sonde à 2 s verrait 7 relevés sur 8
    depuis le cache, et raterait tout mouvement de compteur."""
    client = ApexClient(api_key="k")
    appels = []

    async def faux_fetch(endpoint, params):
        appels.append(endpoint)
        return {"n": len(appels)}

    client._fetch = faux_fetch

    premier = await client.get("bridge", {"uid": "1"})
    second = await client.get("bridge", {"uid": "1"}, sans_cache=True)

    assert premier == {"n": 1}
    assert second == {"n": 2}, "sans_cache doit refaire l'appel"
    assert len(appels) == 2


@pytest.mark.asyncio
async def test_sans_cache_n_empoisonne_pas_le_cache_des_autres():
    """Un relevé de duel ne doit pas devenir la réponse servie au reste du bot."""
    client = ApexClient(api_key="k")
    valeurs = iter([{"v": "frais"}, {"v": "duel"}])

    async def faux_fetch(endpoint, params):
        return next(valeurs)

    client._fetch = faux_fetch

    await client.get("bridge", {"uid": "1"})                    # met "frais" en cache
    await client.get("bridge", {"uid": "1"}, sans_cache=True)   # ne doit RIEN écrire
    assert await client.get("bridge", {"uid": "1"}) == {"v": "frais"}
