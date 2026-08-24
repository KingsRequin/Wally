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
async def test_hors_live_on_sonde_sans_rien_percevoir():
    """La sonde entretient l'historique des totaux même hors live — « combien
    de kills ce mois-ci » compterait faux sans les parties jouées sans stream.

    La PERCEPTION, elle, garde son contrat : hors live, rien au prompt.
    """
    service = _FakeService(_bridge("azrael"))
    w = _watcher(live=False, service=service)
    await w.tick()
    assert service.calls == 1
    assert w.block() is None


@pytest.mark.asyncio
async def test_la_cadence_se_resserre_pendant_le_live():
    from bot.core.apex.watcher import POLL_INTERVAL_IDLE_S, POLL_INTERVAL_LIVE_S

    assert _watcher(live=True)._cadence() == POLL_INTERVAL_LIVE_S
    assert _watcher(live=False)._cadence() == POLL_INTERVAL_IDLE_S
    assert POLL_INTERVAL_LIVE_S < POLL_INTERVAL_IDLE_S


@pytest.mark.asyncio
async def test_hors_live_les_compteurs_sont_quand_meme_historises():
    releves: list[dict] = []

    class _Hist:
        async def enregistrer(self, uid, stats, **kw):
            releves.append({"uid": uid, "stats": stats})
            return len(stats)

    w = _watcher(live=False, service=_FakeService(_bridge("azrael")))
    w._history = _Hist()
    await w.tick()
    assert releves and releves[0]["stats"]


@pytest.mark.asyncio
async def test_le_rp_est_releve_avec_les_autres_compteurs():
    """Le mode d'une partie n'existe NULLE PART dans l'API : ni les trackers
    (« BR Kills » inclut le classé) ni `realtime` ne disent la file de jeu.

    Un RP qui bouge est le seul signal exploitable qu'une partie était classée.
    Sans ce relevé, la courbe ne pourra jamais distinguer les deux.
    """
    releves: list[dict] = []

    class _Hist:
        async def enregistrer(self, uid, stats, **kw):
            releves.append(stats)
            return len(stats)

    w = _watcher(live=True, service=_FakeService(_bridge("azrael")))
    w._history = _Hist()
    await w.tick()
    assert releves[0].get("rank_score") == 6422


@pytest.mark.asyncio
async def test_un_compte_sans_rang_ne_range_pas_de_rp():
    """Pas de rang classé = pas de notion `rank_score` : un zéro se lirait comme
    une chute de RP, donc comme une partie classée perdue."""
    releves: list[dict] = []

    class _Hist:
        async def enregistrer(self, uid, stats, **kw):
            releves.append(stats)
            return len(stats)

    sans_rang = _bridge("azrael")
    sans_rang["global"]["rank"] = {}
    w = _watcher(live=True, service=_FakeService(sans_rang))
    w._history = _Hist()
    await w.tick()
    assert "rank_score" not in releves[0]


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


# ── la progression survit à un redémarrage ──────────────────────────────────


class _MemoryState:
    """Une base réduite à ce que le watcher lui demande."""

    def __init__(self):
        self.rows = {}

    async def get_state(self, key):
        return self.rows.get(key)

    async def set_state(self, key, value):
        self.rows[key] = value


@pytest.mark.asyncio
async def test_le_point_de_depart_survit_a_un_redemarrage():
    """Un rebuild en plein live ne doit pas remettre la progression à zéro."""
    depart = _bridge("azrael")
    plus_tard = json.loads(json.dumps(depart))
    plus_tard["total"]["specialEvent_kills"]["value"] += 9

    state = _MemoryState()
    premier = ApexWatcher(_FakeService(depart), account=("Azrael_ttv", "PC"),
                          is_live=lambda: True, db=state)
    await premier.tick()

    # Nouveau process : même base, même live.
    second = ApexWatcher(_FakeService(plus_tard), account=("Azrael_ttv", "PC"),
                         is_live=lambda: True, db=state)
    await second.tick()

    assert second.progress()["kills"] == 9


@pytest.mark.asyncio
async def test_la_fin_du_live_efface_le_point_de_depart():
    state = _MemoryState()
    live = [True]
    w = ApexWatcher(_FakeService(_bridge("azrael")), account=("Azrael_ttv", "PC"),
                    is_live=lambda: live[0], db=state)
    await w.tick()
    assert state.rows, "le départ n'a pas été rangé"
    live[0] = False
    await w.tick()
    # Le point de départ porte désormais l'identité de son live —
    # `{"live": …, "stats": {…}}` — pour qu'un redémarrage entre deux lives ne
    # fasse pas cumuler les deux sessions. Ce sont les stats qui doivent être
    # vides ; l'enveloppe, elle, reste.
    reste = json.loads(state.rows.get("apex:live_baseline") or "{}")
    assert reste.get("stats", reste) == {}, "le départ du live précédent traîne encore"


@pytest.mark.asyncio
async def test_sans_base_le_watcher_fonctionne_comme_avant():
    w = ApexWatcher(_FakeService(_bridge("azrael")), account=("Azrael_ttv", "PC"),
                    is_live=lambda: True)
    await w.tick()
    assert w.block() is not None


@pytest.mark.asyncio
async def test_chaque_tracker_est_historise_separement():
    """Le défaut du 2026-08-20 : on ne consignait QUE le tracker élu par
    `profile.stats`, élu par priorité d'alias. Azraël a épinglé « Career Kills »
    puis l'a retiré ; l'élu est resté figé et l'historique des kills s'est tu
    quatre jours, sans une alerte. Une série PAR TRACKER, et la lecture retient
    celui qui a bougé.
    """
    releves: list[dict] = []

    class _Hist:
        async def enregistrer(self, uid, stats, **kw):
            releves.append(stats)
            return len(stats)

    w = _watcher(live=True, service=_FakeService(_bridge("azrael")))
    w._history = _Hist()
    await w.tick()
    ranges = releves[0]
    # Les DEUX trackers de « BR Kills », chacun sous sa propre clé.
    assert ranges["kills:specialEvent_kills"] == 92182
    assert ranges["kills:kills"] == 10142
    # Et surtout : plus une seule ligne rangée sous la notion nue, qui serait
    # l'élu — donc le candidat au gel.
    assert "kills" not in ranges


@pytest.mark.asyncio
async def test_la_progression_du_live_prend_le_maximum_jamais_la_somme():
    """`progress()` alimente la perception passive (« +N kills depuis le début
    du live »). Les trackers d'une notion bougent ENSEMBLE à chaque partie : le
    gelé dirait +0 et la somme dirait le double."""
    depart = _bridge("azrael")
    # La situation RÉELLE d'Azraël depuis le 2026-08-20 : « Career Kills »
    # épinglé puis retiré, donc gelé — et c'est lui que `profile.stats` élit,
    # parce qu'il vient avant « BR Kills » dans les alias.
    depart["total"]["career_kills"] = {"name": "Career Kills", "value": 109113}
    arrivee = json.loads(json.dumps(depart))
    arrivee["total"]["specialEvent_kills"]["value"] = 92186   # +4, le vivant
    # `career_kills` et `kills` ne bougent pas : ils sont dépinglés, donc gelés.
    w = _watcher(live=True, service=_FakeService(depart, arrivee))
    await w.tick()
    await w.tick()
    assert w.progress()["kills"] == 4
