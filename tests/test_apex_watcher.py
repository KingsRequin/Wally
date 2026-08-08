# tests/test_apex_watcher.py
"""Le suivi passif du compte du streamer pendant le live.

Même contrat que `StreamFeed` : une voie SANS retour vers l'action. Wally SAIT
qu'Azraël est en partie ; il n'en parle que si on l'y amène. Rien n'appelle
`notify_*`, donc aucune cadence ne se réveille et aucune bulle ne part.
"""
import json
import pathlib

import pytest

from bot.core.apex.watcher import ApexWatcher, current_apex_block

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex"


def _bridge(name):
    return json.loads((FIXTURES / f"bridge_{name}.json").read_text(encoding="utf-8"))


class _FakeService:
    """Un service Apex doublé, qui rend les profils qu'on lui donne, dans l'ordre."""

    def __init__(self, *payloads):
        from bot.core.apex.reader import read_profile

        self._profiles = [read_profile(p) for p in payloads]
        self.calls = 0

    async def fetch_profile(self, player, platform="PC"):
        self.calls += 1
        return self._profiles[min(self.calls - 1, len(self._profiles) - 1)]


def _watcher(live=True, service=None):
    return ApexWatcher(
        service or _FakeService(_bridge("azrael")),
        account=("Azrael_ttv", "PC"),
        is_live=lambda: live,
    )


@pytest.mark.asyncio
async def test_hors_live_on_ne_sonde_pas():
    """Personne ne regarde : chaque appel coûterait pour rien."""
    service = _FakeService(_bridge("azrael"))
    w = _watcher(live=False, service=service)
    await w.tick()
    assert service.calls == 0
    assert w.block() is None


@pytest.mark.asyncio
async def test_pendant_le_live_l_etat_est_lisible_au_prompt():
    w = _watcher()
    await w.tick()
    bloc = w.block()
    assert "Azrael_TTV" in bloc
    assert "Fuse" in bloc          # la légende jouée
    assert "Gold" in bloc          # le rang


@pytest.mark.asyncio
async def test_la_progression_se_compte_depuis_le_debut_du_live():
    """C'est notre réponse à /games, qui nous est fermé."""
    depart = _bridge("azrael")
    plus_tard = json.loads(json.dumps(depart))
    plus_tard["total"]["specialEvent_kills"]["value"] += 14
    plus_tard["total"]["specialEvent_wins"]["value"] += 2

    w = _watcher(service=_FakeService(depart, plus_tard))
    await w.tick()                       # instantané de départ
    await w.tick()                       # plus tard dans le live

    progression = w.progress()
    assert progression["kills"] == 14
    assert progression["wins"] == 2


@pytest.mark.asyncio
async def test_au_premier_passage_la_progression_est_vide_pas_nulle():
    """Sans point de départ, on ne prétend pas que rien n'a bougé."""
    w = _watcher()
    await w.tick()
    assert w.progress() == {}


@pytest.mark.asyncio
async def test_la_fin_du_live_remet_le_compteur_a_zero():
    depart = _bridge("azrael")
    plus_tard = json.loads(json.dumps(depart))
    plus_tard["total"]["specialEvent_kills"]["value"] += 5

    live = [True]
    service = _FakeService(depart, plus_tard)
    w = ApexWatcher(service, account=("Azrael_ttv", "PC"), is_live=lambda: live[0])
    await w.tick()
    live[0] = False
    await w.tick()                       # le live s'arrête : on oublie
    live[0] = True
    await w.tick()                       # nouveau live : nouveau départ
    assert w.progress() == {}


@pytest.mark.asyncio
async def test_une_panne_de_l_api_ne_fait_pas_tomber_le_watcher():
    class _Boom:
        calls = 0

        async def fetch_profile(self, *a, **k):
            raise RuntimeError("API HS")

    w = ApexWatcher(_Boom(), account=("Azrael_ttv", "PC"), is_live=lambda: True)
    await w.tick()                       # ne lève pas
    assert w.block() is None


@pytest.mark.asyncio
async def test_sans_compte_configure_le_watcher_dort():
    service = _FakeService(_bridge("azrael"))
    w = ApexWatcher(service, account=None, is_live=lambda: True)
    await w.tick()
    assert service.calls == 0
    assert w.block() is None


@pytest.mark.asyncio
async def test_le_bloc_global_suit_le_watcher_actif():
    w = _watcher()
    w.activate()
    await w.tick()
    assert current_apex_block() is not None
