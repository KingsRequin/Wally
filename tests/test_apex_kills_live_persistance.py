# tests/test_apex_kills_live_persistance.py
"""Le suivi des kills du live survit au redémarrage (2026-08-20).

LA PANNE : l'owner n'a jamais vu le widget de fin de partie. Le bilan était bien
émis (11 fois le 19/08 dans `app.log`), mais `KillsDuLive` vivait entièrement en
RAM — et il y a eu CINQ redémarrages entre 20 h et 23 h ce soir-là. Chacun
remettait le cumul du soir à zéro et, pire, faisait repartir la partie EN COURS
d'un point de départ inventé ou perdu.

Le déclencheur exact est `premier` : `_kills_live_id` étant un attribut de RAM
initialisé à `""`, tout nouveau process le voyait différent de l'identité du
live et appelait `nouveau_live()`. Une partie commencée avant le rebuild ne
pouvait donc JAMAIS produire de bilan — elle était marquée « point de départ
inconnu », et `show_apex_kills` refuse à juste titre d'afficher un faux zéro.

⚠️ Le délai d'attente après sortie de partie est un `time.monotonic()`, qui
repart de zéro à chaque process : il se range en temps MURAL et se reconvertit.
"""
import pytest

from bot.core.apex.kills_live import KillsDuLive

TRACKERS_A = {"kills": 100, "damage": 5000}
TRACKERS_B = {"kills": 104, "damage": 5800}


def _suivi(mono=None, murale=None):
    return KillsDuLive(horloge=mono, horloge_murale=murale)


def test_le_cumul_du_soir_traverse_un_redemarrage():
    avant = _suivi()
    avant.relever(in_game=True, trackers=TRACKERS_A, premier=False)
    avant.relever(in_game=False, trackers=TRACKERS_B)
    avant.relever(in_game=False, trackers=TRACKERS_B)   # figé : plus rien ne bouge
    assert avant.total == 4 and avant.parties == 1

    apres = _suivi()
    apres.reprendre(avant.instantane())

    assert apres.total == 4
    assert apres.parties == 1


def test_une_partie_en_cours_garde_son_point_de_depart():
    """Le cœur de la panne : rebuild en pleine partie."""
    avant = _suivi()
    avant.relever(in_game=True, trackers=TRACKERS_A, premier=False)

    apres = _suivi()
    apres.reprendre(avant.instantane())

    # La partie se termine APRÈS le redémarrage : son bilan doit être juste.
    assert apres.relever(in_game=False, trackers=TRACKERS_B) is None
    bilan = apres.relever(in_game=False, trackers=TRACKERS_B)
    assert bilan is not None
    assert bilan["partie"] == 4
    assert bilan["total"] == 4


def test_le_delai_d_attente_ne_repart_pas_de_zero():
    """`time.monotonic()` repart à zéro dans le nouveau process. Rangé tel quel,
    l'attente recommencerait — ou expirerait aussitôt."""
    mono = [10_000.0]
    murale = [1_700_000_000.0]
    avant = _suivi(mono=lambda: mono[0], murale=lambda: murale[0])
    avant.relever(in_game=True, trackers=TRACKERS_A, premier=False)
    avant.relever(in_game=False, trackers=TRACKERS_B)      # sortie de partie
    range = avant.instantane()

    # Le process redémarre : 80 s de mur passent, l'horloge monotone repart bas.
    murale[0] += 80
    mono2 = [42.0]
    apres = _suivi(mono=lambda: mono2[0], murale=lambda: murale[0])
    apres.reprendre(range)

    # 80 s écoulées sur les 90 du plafond : il en reste 10, rien n'est figé
    # par le seul délai. Les compteurs, eux, se sont tus → la partie se ferme.
    assert apres._maintenant() - apres._sortie_a == pytest.approx(80.0)


def test_un_instantane_vide_ne_casse_rien():
    suivi = _suivi()
    suivi.reprendre({})
    assert suivi.total == 0 and suivi.parties == 0


def test_un_instantane_corrompu_ne_ressuscite_pas_un_etat_bancal():
    """Un JSON d'une version antérieure, ou tronqué : on repart propre."""
    suivi = _suivi()
    suivi.reprendre({"total": "beaucoup", "base": ["pas", "un", "dict"]})
    assert suivi.total == 0
    assert suivi._base is None


def test_l_instantane_est_serialisable_en_json():
    """Il part dans `bot_state` : un `set` ou un tuple le ferait échouer."""
    import json

    suivi = _suivi()
    suivi.relever(in_game=True, trackers=TRACKERS_A, premier=False)
    suivi.relever(in_game=False, trackers=TRACKERS_B)
    json.dumps(suivi.instantane())     # ne lève pas


# ── le watcher : le cumul du soir traverse le rebuild ─────────────────────

class _Profil:
    def __init__(self, in_game, trackers):
        self.in_game = in_game
        self.kill_trackers = trackers
        self.rank = None
        self.stats = {}
        self.name = "Azrael"
        self.legend = None
        self.state = "online"


class _Service:
    def __init__(self, profils):
        self._profils = list(profils)

    async def fetch_profile(self, *a, **k):
        return self._profils.pop(0) if len(self._profils) > 1 else self._profils[0]


def _base_memoire():
    from unittest.mock import AsyncMock, MagicMock
    db = MagicMock()
    db._v = {}

    async def _set(c, v): db._v[c] = v
    async def _get(c): return db._v.get(c)
    async def _del(c): db._v.pop(c, None)

    db.set_state = AsyncMock(side_effect=_set)
    db.get_state = AsyncMock(side_effect=_get)
    db.delete_state = AsyncMock(side_effect=_del)
    return db


def _watcher(db, profils):
    from bot.core.apex.watcher import ApexWatcher
    return ApexWatcher(
        _Service(profils), account=("Azrael", "PC"), is_live=lambda: True,
        db=db, live_id=lambda: "live-A",
    )


@pytest.mark.asyncio
async def test_le_watcher_reprend_le_cumul_apres_un_rebuild():
    """LA panne du 19/08 : cinq rebuilds, cinq remises à zéro.

    La séquence est celle d'un vrai live : on arrive hors partie (le tout
    premier relevé ne fixe volontairement AUCUN point de départ), on entre en
    partie, on en sort, les compteurs se taisent.
    """
    db = _base_memoire()

    avant = _watcher(db, [_Profil(False, TRACKERS_A), _Profil(True, TRACKERS_A),
                          _Profil(False, TRACKERS_B), _Profil(False, TRACKERS_B)])
    for _ in range(4):
        await avant.tick()
    assert avant._suivi_kills().total == 4

    # Le process meurt et repart : objet neuf, même base.
    apres = _watcher(db, [_Profil(False, TRACKERS_B)])
    await apres.tick()

    assert apres._suivi_kills().total == 4
    assert apres._suivi_kills().parties == 1


@pytest.mark.asyncio
async def test_le_bilan_d_une_partie_commencee_avant_le_rebuild_arrive():
    """Sans reprise, `premier=True` la marquait « départ inconnu » et le widget
    n'affichait jamais rien — le symptôme constaté par l'owner."""
    db = _base_memoire()
    bilans = []

    avant = _watcher(db, [_Profil(False, TRACKERS_A), _Profil(True, TRACKERS_A)])
    await avant.tick()                      # arrivée hors partie
    await avant.tick()                      # partie en cours au moment du rebuild

    apres = _watcher(db, [_Profil(False, TRACKERS_B), _Profil(False, TRACKERS_B)])
    apres._on_partie = bilans.append
    await apres.tick()
    await apres.tick()

    assert bilans and bilans[0]["partie"] == 4


@pytest.mark.asyncio
async def test_le_cumul_d_un_autre_live_n_est_pas_repris():
    from bot.core.apex.watcher import ApexWatcher

    db = _base_memoire()
    avant = _watcher(db, [_Profil(False, TRACKERS_A), _Profil(True, TRACKERS_A),
                          _Profil(False, TRACKERS_B), _Profil(False, TRACKERS_B)])
    for _ in range(4):
        await avant.tick()

    autre = ApexWatcher(_Service([_Profil(False, TRACKERS_B)]),
                        account=("Azrael", "PC"), is_live=lambda: True,
                        db=db, live_id=lambda: "live-B")
    await autre.tick()

    assert autre._suivi_kills().total == 0
