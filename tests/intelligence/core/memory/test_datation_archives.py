"""Un fait rattrapé sur archive porte la date où la chose a été DITE.

Cinq mois de chat PhantomBot entrent d'un coup dans la mémoire
(`scripts/importer_chat_phantombot.py`). Datés d'aujourd'hui, ils passeraient
pour du frais : la réconciliation tranche les contradictions à l'ancienneté,
`get_users_with_recent_facts` régénère le portrait des gens dont un fait a bougé
« récemment », et le repli du journal verse tous les souvenirs connus.

Ces tests tiennent le MÉCANISME de datation, pas le script : c'est le mécanisme
qui vit en production et que le prochain rattrapage réutilisera.
"""
from datetime import datetime

import pytest

from bot.intelligence.memory.facts import (
    AtomicFact, FactCategory, FactStatus, SQLiteFactStore,
)
from bot.intelligence.memory.ingest import MemoryIngest, _Candidate

_FEVRIER = datetime(2026, 2, 20, 0, 0, 0)


def _cand(**kw) -> _Candidate:
    base = dict(subject="alice", predicate="aime", object="apex",
                category="PREF", confidence_source="explicit", importance=0.5)
    base.update(kw)
    return _Candidate(**base)


@pytest.mark.asyncio
async def test_candidat_sans_quand_est_date_de_maintenant(tmp_db_path):
    """Le chemin NORMAL ne bouge pas : sans `quand`, c'est l'heure courante."""
    ingest = MemoryIngest(SQLiteFactStore(tmp_db_path), llm=None)
    fait = ingest._make_fact(_cand(), "twitch:1", FactStatus.ACTIVE)
    assert (datetime.utcnow() - fait.created_at).total_seconds() < 5
    # Chacun a son propre `default_factory` : ils ne tombent pas sur la même
    # microseconde, et ça n'a aucune importance. On vérifie l'ordre de grandeur.
    assert abs((fait.created_at - fait.last_seen_at).total_seconds()) < 1


@pytest.mark.asyncio
async def test_candidat_avec_quand_porte_la_date_dorigine(tmp_db_path):
    ingest = MemoryIngest(SQLiteFactStore(tmp_db_path), llm=None)
    fait = ingest._make_fact(_cand(quand=_FEVRIER), "twitch:1", FactStatus.ACTIVE)
    assert fait.created_at == _FEVRIER
    assert fait.last_seen_at == _FEVRIER


@pytest.mark.asyncio
async def test_confirmer_avec_une_observation_ancienne_ne_rajeunit_pas(tmp_db_path):
    """Une archive de février ne doit pas marquer un fait comme revu aujourd'hui.

    C'est le piège que `quand` ferme : `confirm()` posait `last_seen_at =
    utcnow()` en dur, donc réimporter du vieux rendait « frais » tout fait déjà
    connu — et le portrait du soir serait reparti sur les 373 personnes du chat
    de février.
    """
    store = SQLiteFactStore(tmp_db_path)
    ancien = datetime(2026, 3, 1, 12, 0, 0)
    fid = await store.add(AtomicFact(
        user_id="twitch:1", content="alice aime apex", category=FactCategory.PREF,
        subject="alice", predicate="aime", object_="apex",
        created_at=ancien, last_seen_at=ancien,
    ))
    await store.confirm(fid, _FEVRIER)          # observation ANTÉRIEURE
    faits = await store.get_by_user("twitch:1")
    assert faits[0].last_seen_at == ancien, "une archive ne doit pas rajeunir un fait"
    assert faits[0].support_count == 2, "elle le renforce quand même"


@pytest.mark.asyncio
async def test_confirmer_sans_quand_rafraichit_toujours(tmp_db_path):
    """Le chemin normal garde son effet : une observation d'aujourd'hui date d'aujourd'hui."""
    store = SQLiteFactStore(tmp_db_path)
    vieux = datetime(2026, 2, 1, 12, 0, 0)
    fid = await store.add(AtomicFact(
        user_id="twitch:2", content="bob joue à apex", category=FactCategory.FAIT,
        subject="bob", predicate="joue_a", object_="apex",
        created_at=vieux, last_seen_at=vieux,
    ))
    await store.confirm(fid)
    faits = await store.get_by_user("twitch:2")
    assert faits[0].last_seen_at > vieux


@pytest.mark.asyncio
async def test_une_archive_nefface_pas_un_fait_plus_recent(tmp_db_path):
    """Le passé ne doit pas effacer le présent.

    Vu au premier import de chat PhantomBot : « jubeii1979 est belge », dit en
    février, a remplacé « Jubeii1979 est streamer américain », appris le matin
    même. La réconciliation donne raison au candidat entrant sur toute
    contradiction — juste quand ce qui entre vient d'être dit, faux quand on
    rattrape des mois d'archives.
    """
    store = SQLiteFactStore(tmp_db_path)
    ingest = MemoryIngest(store, llm=None)
    recent = AtomicFact(
        user_id="twitch:9", content="jubeii1979 est américain",
        category=FactCategory.FAIT, subject="jubeii1979", predicate="est",
        object_="américain",
        created_at=datetime(2026, 8, 28, 9, 0), last_seen_at=datetime(2026, 8, 28, 9, 0),
    )
    await store.add(recent)
    assert ingest._trop_vieux_pour_remplacer(_cand(quand=_FEVRIER), recent) is True


@pytest.mark.asyncio
async def test_une_archive_remplace_un_fait_plus_ancien_quelle(tmp_db_path):
    """Elle garde le droit de corriger ce qui la précède."""
    ingest = MemoryIngest(SQLiteFactStore(tmp_db_path), llm=None)
    plus_vieux = AtomicFact(
        user_id="twitch:9", content="x est y", category=FactCategory.FAIT,
        subject="x", predicate="est", object_="y",
        created_at=datetime(2026, 1, 5), last_seen_at=datetime(2026, 1, 5),
    )
    assert ingest._trop_vieux_pour_remplacer(_cand(quand=_FEVRIER), plus_vieux) is False


@pytest.mark.asyncio
async def test_le_chemin_normal_nest_jamais_freine(tmp_db_path):
    """Sans `quand`, la garde ne s'applique pas — la prod garde son comportement."""
    ingest = MemoryIngest(SQLiteFactStore(tmp_db_path), llm=None)
    recent = AtomicFact(
        user_id="twitch:9", content="x est y", category=FactCategory.FAIT,
        subject="x", predicate="est", object_="y",
        created_at=datetime(2026, 8, 28, 9, 0), last_seen_at=datetime(2026, 8, 28, 9, 0),
    )
    assert ingest._trop_vieux_pour_remplacer(_cand(), recent) is False


@pytest.mark.asyncio
async def test_un_fait_date_avec_fuseau_ne_fait_pas_lever(tmp_db_path):
    """`created_at` mélange l'UTC naïf et l'ISO à offset selon le chemin d'écriture."""
    from datetime import timezone
    ingest = MemoryIngest(SQLiteFactStore(tmp_db_path), llm=None)
    aware = AtomicFact(
        user_id="twitch:9", content="x est y", category=FactCategory.FAIT,
        subject="x", predicate="est", object_="y",
        created_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )
    assert ingest._trop_vieux_pour_remplacer(_cand(quand=_FEVRIER), aware) is True


# ── Ce que le PROMPT montre de l'âge d'un fait ────────────────────────────────

def _faux_fait(created_at, expires_at=None):
    class F:
        pass
    f = F()
    f.created_at, f.expires_at = created_at, expires_at
    return f


def test_un_fait_durable_recent_nest_pas_annote():
    """Le cas courant ne change pas : rien n'alourdit le prompt sans raison."""
    from bot.intelligence.memory.service import MemoryService
    assert MemoryService._fact_freshness(_faux_fait(datetime.utcnow())) == ""


def test_un_fait_durable_de_six_mois_est_date():
    """Sans date, « xeforce_ est Platine 2 » lu six mois plus tard est un mensonge."""
    from datetime import timedelta

    from bot.intelligence.memory.service import MemoryService
    vieux = datetime.utcnow() - timedelta(days=190)
    assert "mois" in MemoryService._fact_freshness(_faux_fait(vieux))


def test_un_ephemere_du_jour_garde_sa_formule():
    from bot.intelligence.memory.service import MemoryService
    f = _faux_fait(datetime.utcnow(), expires_at=datetime(2030, 1, 1))
    assert MemoryService._fact_freshness(f) == " (dit plus tôt aujourd'hui)"
