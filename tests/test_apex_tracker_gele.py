# tests/test_apex_tracker_gele.py
"""Le tracker GELÉ ne doit plus éteindre l'historique (2026-08-24).

Le 2026-08-20 à 18h31, Azraël a épinglé « Career Kills » (109 113) puis l'a
retiré. `_read_stats()` élit un tracker par PRIORITÉ D'ALIAS — « Career Kills »
avant « BR Kills » — et c'est cet élu que l'historisation consignait. Dépinglé,
il est figé : quatre jours durant, plus une seule ligne de kills n'a été écrite,
alors que le compteur du live en comptait 34 le 24 au matin. « La courbe de ce
stream » n'avait plus de quoi être tracée, et rien ne le signalait.

Ces tests tiennent la règle qui répare : on consigne TOUS les trackers, et on
retient à la lecture celui qui a le plus GAGNÉ — jamais leur somme.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from bot.core.apex.history import ApexHistory, aplatir_trackers
from bot.core.apex.reader import read_profile, read_stat_trackers
from bot.db.database import Database

HEURE = 3600.0
UID = "2274044345"


# ── la lecture du payload ────────────────────────────────────────────────────

def _payload(**valeurs) -> dict:
    total = {cle: {"name": nom, "value": v} for cle, (nom, v) in valeurs.items()}
    return {"global": {"name": "Azrael", "uid": UID, "platform": "PC"}, "total": total}


def test_tous_les_trackers_dune_notion_sont_rendus():
    """Trois trackers de kills, trois séries — aucun élu, aucun jeté."""
    trackers = read_stat_trackers(_payload(
        career_kills=("Career Kills", 109_113),
        specialEvent_kills=("BR Kills", 94_891),
        kills=("BR Kills", 10_203),
    ))
    assert trackers["kills"] == {
        "career_kills": 109_113, "specialEvent_kills": 94_891, "kills": 10_203
    }


def test_un_tracker_hors_notion_connue_est_ignore():
    """« Bamboozles » n'est pas une notion suivie : il n'a rien à faire là."""
    trackers = read_stat_trackers(_payload(
        bamboozles=("Bamboozles", 2456), specialEvent_wins=("BR Wins", 3612),
    ))
    assert trackers == {"wins": {"specialEvent_wins": 3612}}


def test_le_profil_porte_les_trackers():
    """C'est par là que le watcher les reçoit : sans ce câblage, rien n'est écrit."""
    profil = read_profile(_payload(specialEvent_kills=("BR Kills", 94_891)))
    assert profil is not None
    assert profil.trackers == {"kills": {"specialEvent_kills": 94_891}}


def test_un_payload_casse_ne_leve_pas():
    assert read_stat_trackers({"total": None}) == {}
    assert read_stat_trackers({"total": {"x": ["pas un dict"]}}) == {}
    assert read_stat_trackers("pas un dict") == {}


def test_la_cle_rangee_a_un_seul_ecrivain():
    assert aplatir_trackers({"kills": {"specialEvent_kills": 1}}) == {
        "kills:specialEvent_kills": 1
    }


# ── la lecture de l'historique ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def history(tmp_path):
    base = await Database.create(str(tmp_path / "test.db"))
    try:
        yield ApexHistory(base)
    finally:
        await base.close()


async def _ranger(history, t: float, **par_cle: int) -> None:
    await history.enregistrer(UID, par_cle, maintenant=t)


@pytest.mark.asyncio
async def test_le_tracker_gele_ne_fait_pas_taire_la_courbe(history):
    """LE test de régression. Le gelé est le plus HAUT ; c'est l'autre qui parle."""
    t0 = 1_000_000.0
    for i, kills in enumerate((94_500, 94_520, 94_555)):
        await _ranger(history, t0 + i * 600,
                      **{"kills:career_kills": 109_113,
                         "kills:specialEvent_kills": kills})
    prog = await history.progression(UID, "kills", t0 - 1)
    assert prog is not None
    assert prog.gain == 55                       # 94 555 − 94 500, et pas 0
    assert len(prog.points) == 3                 # de quoi tracer la courbe


@pytest.mark.asyncio
async def test_les_trackers_ne_sadditionnent_jamais(history):
    """Ils bougent ENSEMBLE à chaque partie : les sommer quadruplerait le score."""
    t0 = 1_000_000.0
    await _ranger(history, t0, **{"kills:specialEvent_kills": 100, "kills:kills": 50})
    await _ranger(history, t0 + 600,
                  **{"kills:specialEvent_kills": 110, "kills:kills": 60})
    prog = await history.progression(UID, "kills", t0 - 1)
    assert prog is not None and prog.gain == 10   # le maximum, pas 20


@pytest.mark.asyncio
async def test_les_lignes_de_lancien_format_restent_lues(history):
    """Cent jours de relevés sont rangés sous la seule notion. Ils comptent."""
    t0 = 1_000_000.0
    await _ranger(history, t0, kills=1000)
    await _ranger(history, t0 + 600, kills=1030)
    prog = await history.progression(UID, "kills", t0 - 1)
    assert prog is not None and prog.gain == 30


@pytest.mark.asyncio
async def test_le_rp_nest_pas_aspire_par_le_groupe_dune_autre_notion(history):
    """`_` est un JOKER en SQL : un `LIKE` mal placé ramènerait des rangs
    ici. Le test vaut pour la requête, pas pour la notion."""
    t0 = 1_000_000.0
    await _ranger(history, t0, **{"rank_score": 10_000, "kills:kills": 5})
    await _ranger(history, t0 + 600, **{"rank_score": 10_100, "kills:kills": 9})
    prog = await history.progression(UID, "kills", t0 - 1)
    assert prog is not None and prog.gain == 4
    assert [v for _, v in prog.points] == [5, 9]


@pytest.mark.asyncio
async def test_sans_aucun_releve_on_ne_rend_rien(history):
    assert await history.progression(UID, "kills", 0.0) is None


@pytest.mark.asyncio
async def test_la_consultation_precedente_se_cherche_sur_tout_le_groupe(history):
    """Chercher sur un seul tracker remonterait au jour de son dépinglage."""
    t0 = 1_000_000.0
    await _ranger(history, t0, **{"kills:career_kills": 109_113,
                                  "kills:specialEvent_kills": 94_500})
    maintenant = t0 + 4 * HEURE
    await _ranger(history, maintenant, **{"kills:specialEvent_kills": 94_624})
    # `avant` est l'instant du relevé courant, déjà écrit : l'appelant réel
    # consigne AVANT de comparer, et la borne est stricte.
    prog = await history.depuis_derniere_consultation(UID, "kills", avant=maintenant)
    assert prog is not None and prog.gain == 124
