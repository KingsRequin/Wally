"""Tests Phase 5 — script de nettoyage one-shot de la dette mentale.

Couvre les fonctions pures de clustering pondéré IDF et la couche DB
(dry-run vs --apply, cumul de support, idempotence).
"""
import sqlite3

import pytest

import scripts.dedupe_mental_state as dd


# --------------------------------------------------------------------------- #
# Fonctions pures
# --------------------------------------------------------------------------- #

def test_tokens_normalises_and_drops_short_and_stopwords():
    toks = dd._tokens("Le clip Apex avec POLYLROSE n'existe pas !")
    assert "polylrose" in toks
    assert "apex" in toks
    assert "clip" in toks
    # stopwords / mots courts retirés
    assert "le" not in toks
    assert "n" not in toks  # 1 car -> retiré
    # ponctuation supprimée : pas de token avec apostrophe
    assert all("'" not in t for t in toks)


def test_idf_rare_token_weighs_more_than_common():
    docs = [
        {"jubeii", "kingsrequin", "demander"},
        {"kingsrequin", "demander", "animes"},
        {"kingsrequin", "demander", "downloads"},
    ]
    idf = dd._idf(docs)
    # "jubeii" n'apparaît qu'une fois -> idf plus élevé que "kingsrequin" (partout)
    assert idf["jubeii"] > idf["kingsrequin"]


def test_weighted_jaccard_identical_is_one():
    a = {"jubeii", "apex", "origine"}
    idf = dd._idf([a, {"autre"}])
    assert dd._weighted_jaccard(a, set(a), idf) == pytest.approx(1.0)


def test_weighted_jaccard_disjoint_is_zero():
    a, b = {"jubeii"}, {"animes"}
    idf = dd._idf([a, b])
    assert dd._weighted_jaccard(a, b, idf) == pytest.approx(0.0)


def test_cluster_groups_paraphrases_sharing_rare_token():
    # 3 désirs jubeii (paraphrases) + 1 sans rapport
    items = {
        1: dd._tokens("jubeii1979 / plays Apex Legends — origine du souvenir floue"),
        2: dd._tokens("Qui est jubeii1979 ? Ce souvenir plays Apex Legends est suspect"),
        3: dd._tokens("Creuser jubeii1979 / plays Apex Legends — origine du souvenir"),
        4: dd._tokens("Demander à KingsRequin quels animes il regarde en ce moment"),
    }
    idf = dd._idf(list(items.values()))
    clusters = dd.cluster(items, threshold=0.4, idf=idf)
    # le trio jubeii est regroupé, le 4e est seul
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 3]
    big = next(c for c in clusters if len(c) == 3)
    assert set(big) == {1, 2, 3}


def test_plan_merges_keeps_most_recent_and_sums_support():
    facts = [
        dd.Fact(id=10, content="jubeii origine Apex souvenir", last_seen_at="2026-06-25T01:00", support_count=1),
        dd.Fact(id=20, content="jubeii origine Apex souvenir floue", last_seen_at="2026-06-26T01:00", support_count=2),
        dd.Fact(id=30, content="jubeii origine Apex souvenir suspect", last_seen_at="2026-06-24T01:00", support_count=1),
        dd.Fact(id=99, content="demander animes KingsRequin", last_seen_at="2026-06-26T02:00", support_count=1),
    ]
    clusters = dd.plan_merges(facts, threshold=0.4)
    # un seul cluster fusionnable (le trio jubeii)
    merges = [c for c in clusters if c.losers]
    assert len(merges) == 1
    m = merges[0]
    assert m.survivor.id == 20            # le plus récent
    assert {f.id for f in m.losers} == {10, 30}
    assert m.merged_support == 4          # 1+2+1


def test_plan_merges_idempotent_on_deduped_set():
    # ensemble déjà dédupliqué (tokens disjoints) -> aucune fusion
    facts = [
        dd.Fact(id=1, content="jubeii origine apex", last_seen_at="2026-06-26T01:00", support_count=1),
        dd.Fact(id=2, content="demander animes kingsrequin", last_seen_at="2026-06-26T01:00", support_count=1),
        dd.Fact(id=3, content="cluth valorant ascendant tracker", last_seen_at="2026-06-26T01:00", support_count=1),
    ]
    clusters = dd.plan_merges(facts, threshold=0.4)
    assert all(not c.losers for c in clusters)


# --------------------------------------------------------------------------- #
# Couche DB
# --------------------------------------------------------------------------- #

def _make_db(tmp_path):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE atomic_facts (
            id INTEGER PRIMARY KEY,
            user_id TEXT, content TEXT, category TEXT,
            support_count INTEGER DEFAULT 1, confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'active', last_seen_at TEXT
        )"""
    )
    rows = [
        # trio jubeii (DESIRE) à fusionner
        (1, "wally:self", "jubeii1979 / plays Apex Legends — origine du souvenir floue", "DESIRE", 1, 1.0, "active", "2026-06-25T01:00"),
        (2, "wally:self", "Qui est jubeii1979 ? plays Apex Legends — origine suspecte", "DESIRE", 2, 1.0, "active", "2026-06-26T01:00"),
        (3, "wally:self", "Creuser jubeii1979 / plays Apex Legends — origine du souvenir", "DESIRE", 1, 1.0, "active", "2026-06-24T01:00"),
        # désir isolé
        (4, "wally:self", "Demander à KingsRequin quels animes il regarde", "DESIRE", 1, 1.0, "active", "2026-06-26T02:00"),
        # pseudo-souvenir curé
        (5, "discord:174", "jubeii1979 plays Apex Legends", "FAIT", 1, 0.7, "active", "2026-06-20T01:00"),
    ]
    conn.executemany(
        "INSERT INTO atomic_facts VALUES (?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return db, conn


def test_apply_merges_archives_losers_and_sums_support(tmp_path):
    db, conn = _make_db(tmp_path)
    facts = dd.load_facts(conn, "DESIRE", "wally:self", "active")
    clusters = dd.plan_merges(facts, threshold=0.4)
    dd.apply_merges(conn, clusters)
    conn.commit()
    # #2 survivant (plus récent) : support cumulé 4 ; #1 et #3 archivés
    surv = conn.execute("SELECT support_count, status FROM atomic_facts WHERE id=2").fetchone()
    assert surv == (4, "active")
    for lid in (1, 3):
        st = conn.execute("SELECT status FROM atomic_facts WHERE id=?", (lid,)).fetchone()[0]
        assert st == "archived"
    # #4 intact
    assert conn.execute("SELECT status FROM atomic_facts WHERE id=4").fetchone()[0] == "active"


def test_apply_pseudo_sets_needs_review_and_lowers_confidence(tmp_path):
    db, conn = _make_db(tmp_path)
    dd.apply_pseudo(conn, [5])
    conn.commit()
    row = conn.execute("SELECT status, confidence FROM atomic_facts WHERE id=5").fetchone()
    assert row[0] == "needs_review"
    assert row[1] <= 0.3


def test_second_run_is_idempotent(tmp_path):
    db, conn = _make_db(tmp_path)
    facts = dd.load_facts(conn, "DESIRE", "wally:self", "active")
    dd.apply_merges(conn, dd.plan_merges(facts, threshold=0.4))
    conn.commit()
    # 2e run : on ne charge que les actifs -> plus de doublon -> 0 fusion
    facts2 = dd.load_facts(conn, "DESIRE", "wally:self", "active")
    clusters2 = dd.plan_merges(facts2, threshold=0.4)
    assert all(not c.losers for c in clusters2)
