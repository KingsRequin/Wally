"""Passe de ménage nocturne : un utilisateur par nuit, tri des doublons par le LLM.

Le mécanisme existait (`d2a8890`) puis a été remplacé par un stub vide lors de la
migration V1→V2 (`77ffb94`, « replace run_memory_cleanup body with no-op stub ») —
il lisait `self._memory.store`, supprimé avec la V1. Sept semaines plus tard la
base portait cinq formulations du même fait pour un seul utilisateur :

    18:07:36  A récemment récupéré sa connexion internet
    18:08:17  A eu des problèmes de connexion récemment
    18:08:58  A eu des problèmes de connexion récemment (récupérée mardi)
    18:09:45  Cluth a récemment récupéré sa connexion internet

La réconciliation live (`MemoryIngest`) n'attrape que les faits porteurs d'un
triplet S-P-O valide ; le reste tombe en `memory.add()` verbatim, qui ne dédupe
que le texte exact. Sans passe de rattrapage, les paraphrases s'empilent.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.database import Database
from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.journal import DailyJournal
from bot.intelligence.memory.facts import (
    AtomicFact,
    FactCategory,
    FactStatus,
    SQLiteFactStore,
)


@pytest.fixture
async def contexte(tmp_path):
    """DB réelle (bot_state + questions) et store réel sur le même fichier."""
    chemin = str(tmp_path / "wally.db")
    db = await Database.create(chemin)
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)

    memoire = MagicMock()
    memoire.fact_store = store
    memoire.cleanup_expired_facts = AsyncMock(return_value=0)

    config = MagicMock()
    config.bot.journal_time = "21:00"
    llm = MagicMock()
    journal = DailyJournal(config, MagicMock(), llm, MagicMock(), memoire, db=db)

    yield journal, store, llm, db
    await db.close()


def _reponse_llm(llm, charge: dict) -> None:
    """Branche le LLM secondaire sur une réponse JSON fixe."""
    llm.complete = AsyncMock(return_value=json.dumps(charge))


async def _peupler(store, uid: str, contenus: list[str]) -> list[int]:
    ids = []
    for contenu in contenus:
        ids.append(
            await store.add(
                AtomicFact(user_id=uid, content=contenu, category=FactCategory.FAIT)
            )
        )
    return ids


async def _statuts(store, ids: list[int]) -> list[str]:
    faits = {f.id: f for f in await store.get_by_user("discord:610", status=FactStatus.ACTIVE)}
    return ["active" if i in faits else "absent" for i in ids]


# ── Le cœur : les doublons repérés par le LLM sont archivés ──────────────────

async def test_les_doublons_designes_sont_archives(contexte):
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [
        "A récemment récupéré sa connexion internet",
        "A eu des problèmes de connexion récemment",
        "A eu des problèmes de connexion récemment (récupérée mardi)",
        "Cluth a récemment récupéré sa connexion internet",
        "Est classé Diamant 3 sur Valorant",
        "Joue à Apex Legends",
    ])
    _reponse_llm(llm, {
        "delete": [
            {"index": 0, "duplicate_of": 2},
            {"index": 1, "duplicate_of": 2},
            {"index": 3, "duplicate_of": 2},
        ],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert {f.id for f in restants} == {ids[2], ids[4], ids[5]}
    archives = await store.get_by_user("discord:610", status=FactStatus.ARCHIVED)
    assert {f.id for f in archives} == {ids[0], ids[1], ids[3]}


async def test_une_reformulation_remplace_le_contenu(contexte):
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [
        "A déménagé à Lyon le mois dernier",
        "Joue à Apex", "Joue à Valorant", "Aime le café", "Est dev",
    ])
    _reponse_llm(llm, {
        "delete": [],
        "update": [{"index": 0, "new_text": "Habite à Lyon"}],
        "questions": [],
    })

    await journal.run_memory_cleanup()

    faits = {f.id: f.content for f in await store.get_by_user("discord:610")}
    assert faits[ids[0]] == "Habite à Lyon"


# ── Sélection de la personne du soir ─────────────────────────────────────────

async def test_wally_self_est_exclu_du_tri(contexte):
    """3,1 Mo d'auto-narratif : hors fenêtre de contexte, et une dynamique à part."""
    journal, store, llm, _ = contexte
    await _peupler(store, "wally:self", [f"pensée {i}" for i in range(40)])
    _reponse_llm(llm, {"delete": [{"index": 0, "duplicate_of": 1}], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    llm.complete.assert_not_awaited()
    restants = await store.get_by_user("wally:self", status=FactStatus.ACTIVE)
    assert len(restants) == 40


async def test_un_utilisateur_trop_maigre_est_ignore(contexte):
    """Sous le seuil, il n'y a rien à trier — on ne paie pas un appel LLM."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", ["Joue à Apex", "Aime le café"])
    _reponse_llm(llm, {"delete": [{"index": 0, "duplicate_of": 1}], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    llm.complete.assert_not_awaited()


async def test_une_seule_personne_par_nuit(contexte):
    journal, store, llm, _ = contexte
    for uid in ("discord:610", "discord:973", "discord:182"):
        await _peupler(store, uid, [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    assert llm.complete.await_count == 1


async def test_la_rotation_change_de_personne_chaque_nuit(contexte):
    """Sans mémoire du dernier passage, la même personne serait triée sans fin."""
    journal, store, llm, _ = contexte
    # Contenus distincts : c'est le seul moyen de reconnaître, dans le prompt
    # envoyé, de quelle personne il s'agit.
    for uid in ("discord:610", "discord:973", "discord:182"):
        await _peupler(store, uid, [f"{uid} joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    vus = []
    for _ in range(3):
        await journal.run_memory_cleanup()
        envoye = llm.complete.await_args.args[1][0]["content"]
        vus.append(next(u for u in ("discord:610", "discord:973", "discord:182") if u in envoye))

    assert len(set(vus)) == 3, f"trois nuits doivent trier trois personnes distinctes, vu {vus}"


# ── Qui passe en premier ─────────────────────────────────────────────────────
#
# L'ordre est : jamais trié d'abord, sinon le plus anciennement trié, et à
# égalité le plus gros stock. Ces tests fixent ce comportement — envisagé un
# moment de prioriser plutôt « qui a le plus accumulé depuis son dernier tri »,
# abandonné : aucun cas réaliste ne départage les deux règles autrement, et
# prioriser le volume ouvre une famine (un bavard permanent monopoliserait le
# cron) qu'il faudrait ensuite corriger par un garde-fou d'ancienneté — soit la
# règle actuelle, en plus compliqué.

async def _marquer_trie(journal, uid: str, quand: datetime) -> None:
    etat = json.loads(await journal._db.get_state("memory_cleanup_last_pass") or "{}")
    etat[uid] = quand.isoformat()
    await journal._db.set_state("memory_cleanup_last_pass", json.dumps(etat))


async def test_a_anciennete_egale_le_plus_gros_stock_passe_devant(contexte):
    """C'est là que les doublons coûtent le plus au budget de contexte."""
    journal, store, llm, _ = contexte
    hier = datetime.utcnow() - timedelta(days=1)
    for uid in ("discord:610", "discord:973"):
        await _peupler(store, uid, [f"{uid} joue à Apex Legends, partie {i}" for i in range(6)])
        await _marquer_trie(journal, uid, hier)
    await _peupler(store, "discord:973", [
        f"discord:973 joue à Valorant en ranked, session {i}" for i in range(10)
    ])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "discord:973" in envoye


async def test_une_personne_jamais_triee_reste_prioritaire(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"discord:610 joue à Apex, partie {i}" for i in range(30)])
    await _marquer_trie(journal, "discord:610", datetime.utcnow() - timedelta(hours=1))
    await _peupler(store, "discord:973", [f"discord:973 joue à Apex, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "discord:973" in envoye


async def test_sans_rien_de_neuf_lanciennete_tranche(contexte):
    journal, store, llm, _ = contexte
    for uid, jours in (("discord:610", 2), ("discord:973", 20)):
        await _peupler(store, uid, [f"{uid} joue à Apex, partie {i}" for i in range(6)])
        await _marquer_trie(journal, uid, datetime.utcnow() - timedelta(days=jours))
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "discord:973" in envoye, "le plus anciennement trié doit passer"


async def test_personne_ne_meurt_de_faim(contexte):
    """Un bavard permanent ne monopolise pas le cron : l'ancienneté prime sur le
    volume, donc quelqu'un oublié depuis deux mois repasse devant."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"discord:610 joue à Apex, partie {i}" for i in range(6)])
    await _marquer_trie(journal, "discord:610", datetime.utcnow() - timedelta(days=60))
    await _peupler(store, "discord:973", [f"discord:973 joue à Apex, partie {i}" for i in range(6)])
    await _marquer_trie(journal, "discord:973", datetime.utcnow() - timedelta(hours=2))
    # 973 vient d'accumuler beaucoup
    await _peupler(store, "discord:973", [
        f"discord:973 joue à Valorant, session {i}" for i in range(20)
    ])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "discord:610" in envoye


# ── Toute suppression doit nommer son remplaçant ─────────────────────────────
#
# Mesuré en prod sur une liste DÉJÀ triée : `deepseek-v4-flash` proposait encore
# de supprimer 25 souvenirs sur 60, dont « héberge Wally sur son serveur
# personnel », « Code des bots, serveurs et stacks *arr », « a un ami appelé
# Azra » — tous uniques, aucun équivalent dans la liste. La consigne écrite dans
# le prompt (« ne jette jamais un souvenir unique ») ne tient pas. Le code exige
# donc un `duplicate_of` vérifiable : sans remplaçant nommé, pas de suppression.

async def test_une_suppression_sans_remplacant_est_refusee(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [{"index": 1}], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 6


async def test_un_index_nu_ne_suffit_plus_a_supprimer(contexte):
    """L'ancien format `delete: [0, 3]` ne dit pas de quoi c'est le doublon."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [0, 3], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 6


async def test_une_suppression_justifiee_est_appliquee(contexte):
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [
        "Joue à Valorant", "Cluth joue à Valorant",
        "Aime le café", "Est dev", "Habite à Lyon", "A un chien",
    ])
    _reponse_llm(llm, {
        "delete": [{"index": 0, "duplicate_of": 1}],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = {f.id for f in await store.get_by_user("discord:610", status=FactStatus.ACTIVE)}
    assert ids[0] not in restants and ids[1] in restants


async def test_un_remplacant_lui_meme_supprime_ne_vaut_pas(contexte):
    """Deux souvenirs qui se désignent l'un l'autre : les supprimer tous les deux
    efface l'information au lieu de la dédupliquer."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {
        "delete": [{"index": 0, "duplicate_of": 1}, {"index": 1, "duplicate_of": 0}],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 5, "un des deux doit survivre"


async def test_un_remplacant_sans_rapport_est_refuse(contexte):
    """Mesuré en prod : le modèle a désigné « est le créateur de Wally » comme
    remplaçant de « joue à League of Legends, classé Grand Clash ». `duplicate_of`
    borne le volume, pas la véracité du lien — deux souvenirs qui ne partagent
    que le pseudo n'ont rien à voir."""
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [
        "KingsRequin est le créateur de Wally",
        "KingsRequin joue à League of Legends et est classé Grand Clash",
        "KingsRequin héberge Wally sur son serveur personnel",
        "KingsRequin regarde des animes sur Jellyfin",
        "KingsRequin code des bots et des stacks *arr",
        "KingsRequin a un ami appelé Azra",
    ])
    _reponse_llm(llm, {
        "delete": [{"index": 1, "duplicate_of": 0}], "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = {f.id for f in await store.get_by_user("discord:610", status=FactStatus.ACTIVE)}
    assert ids[1] in restants


async def test_un_vrai_doublon_reste_supprimable(contexte):
    """La garde lexicale ne doit pas bloquer le ménage légitime : deux
    formulations du même fait partagent forcément des mots porteurs."""
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [
        "Est classé Diamond 3 sur Valorant avec un MMR Ascendant 1-2",
        "Est rang Ascendant à Valorant",
        "KingsRequin héberge Wally sur son serveur personnel",
        "KingsRequin regarde des animes sur Jellyfin",
        "KingsRequin code des bots et des stacks *arr",
        "KingsRequin a un ami appelé Azra",
    ])
    _reponse_llm(llm, {
        "delete": [{"index": 1, "duplicate_of": 0}], "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = {f.id for f in await store.get_by_user("discord:610", status=FactStatus.ACTIVE)}
    assert ids[1] not in restants and ids[0] in restants


async def test_un_remplacant_hors_bornes_est_refuse(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {
        "delete": [{"index": 1, "duplicate_of": 99}, {"index": 2, "duplicate_of": 2}],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 6


# ── Garde-fous ───────────────────────────────────────────────────────────────

async def test_un_effacement_massif_est_refuse(contexte):
    """Un LLM qui déraille ne doit pas pouvoir vider la mémoire d'une personne."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(10)])
    _reponse_llm(llm, {"delete": list(range(10)), "update": [], "questions": []})

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 10, "aucun fait ne doit partir sur un verdict aberrant"


async def test_un_gros_menage_legitime_passe_quand_meme(contexte):
    """Le seuil doit laisser respirer le vrai backlog : sur un lot réel de 60
    souvenirs, quinze lignes disaient « joue à Valorant ». Un garde-fou trop bas
    bloque exactement les lots qui ont le plus besoin d'être nettoyés."""
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(10)])
    _reponse_llm(llm, {
        "delete": [{"index": i, "duplicate_of": 9} for i in range(7)],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert {f.id for f in restants} == {ids[7], ids[8], ids[9]}


async def test_un_index_hors_bornes_ne_casse_pas_la_passe(contexte):
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {
        "delete": [
            {"index": 1, "duplicate_of": 0},
            {"index": 99, "duplicate_of": 0},
            {"index": -3, "duplicate_of": 0},
        ],
        "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert {f.id for f in restants} == {ids[0], ids[2], ids[3], ids[4], ids[5]}


async def test_un_llm_en_panne_ne_fait_pas_tomber_le_cron(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    llm.complete = AsyncMock(side_effect=RuntimeError("DeepSeek indisponible"))

    await journal.run_memory_cleanup()  # ne doit pas lever

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 6


async def test_un_echec_ne_bloque_pas_la_rotation_a_jamais(contexte):
    """Sinon une personne dont le tri plante monopolise le cron toutes les nuits
    et plus personne d'autre n'est jamais nettoyé."""
    journal, store, llm, _ = contexte
    for uid in ("discord:610", "discord:973"):
        await _peupler(store, uid, [f"{uid} joue à Apex Legends, partie {i}" for i in range(6)])
    llm.complete = AsyncMock(side_effect=RuntimeError("DeepSeek indisponible"))

    await journal.run_memory_cleanup()
    premier = llm.complete.await_args.args[1][0]["content"]
    await journal.run_memory_cleanup()
    second = llm.complete.await_args.args[1][0]["content"]

    assert premier != second, "la nuit suivante doit passer à quelqu'un d'autre"


async def test_une_reponse_illisible_ne_touche_a_rien(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    llm.complete = AsyncMock(return_value="désolé, je n'ai pas compris")

    await journal.run_memory_cleanup()

    restants = await store.get_by_user("discord:610", status=FactStatus.ACTIVE)
    assert len(restants) == 6


async def test_le_ttl_reste_purge_meme_sans_store(contexte):
    """La passe LLM est un ajout : elle ne doit pas évincer le ménage existant."""
    journal, _, llm, _db = contexte
    journal._memory.fact_store = None

    await journal.run_memory_cleanup()

    journal._memory.cleanup_expired_facts.assert_awaited_once()


async def test_des_dates_avec_et_sans_fuseau_cohabitent(contexte):
    """La base porte les deux formes : `2026-07-10T18:07:01+00:00` pour les faits
    passés par l'ingest, et de l'UTC naïf pour les autres. Les trier ensemble
    lève `can't compare offset-naive and offset-aware datetimes` — le tri entier
    tombait avant même d'appeler le LLM."""
    journal, store, llm, _ = contexte
    naif = datetime(2026, 7, 10, 18, 7, 1)
    avec_fuseau = datetime(2026, 7, 10, 18, 9, 45, tzinfo=timezone.utc)
    for i, quand in enumerate([naif, avec_fuseau, naif, avec_fuseau, naif, avec_fuseau]):
        await store.add(AtomicFact(
            user_id="discord:610", content=f"fait {i}",
            category=FactCategory.FAIT, created_at=quand,
        ))
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    llm.complete.assert_awaited_once()


# ── Découpage en lots ────────────────────────────────────────────────────────
#
# Mesuré en prod sur les 298 souvenirs de kassandreyunikon : envoyés d'un bloc,
# `deepseek-v4-flash` renvoie une réponse tronquée (plafond de 1000 tokens en
# sortie) ET part en énumération mécanique — 232 index sur 298 marqués à
# supprimer. Le format « rends-moi tous les index » ne tient pas à cette échelle.

async def test_les_souvenirs_sont_tries_par_lots(contexte):
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(130)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    assert llm.complete.await_count == 3, "130 souvenirs = 3 lots de 60"


async def test_les_index_sont_locaux_au_lot(contexte):
    """Chaque lot est renuméroté à partir de 0 : supprimer l'index 0 du 2e lot
    doit viser le 61e souvenir, pas le premier."""
    journal, store, llm, _ = contexte
    ids = await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(70)])
    _reponse_llm(llm, {
        "delete": [{"index": 0, "duplicate_of": 1}], "update": [], "questions": [],
    })

    await journal.run_memory_cleanup()

    archives = {f.id for f in await store.get_by_user("discord:610", status=FactStatus.ARCHIVED)}
    assert archives == {ids[0], ids[60]}


async def test_le_plafond_de_sortie_est_releve_pour_le_verdict(contexte):
    """Le rôle secondaire est câblé à 1000 tokens : un verdict portant des
    dizaines d'index et des reformulations est coupé en plein JSON."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    assert llm.complete.await_args.kwargs.get("max_tokens", 0) >= 4000


# ── Ce que le LLM reçoit ─────────────────────────────────────────────────────

async def test_le_prompt_porte_les_dates_pour_arbitrer_les_doublons(contexte):
    """Le prompt demande de « comparer les dates entre crochets [YYYY-MM-DD] »
    pour garder le plus récent : sans elles, l'arbitrage est aveugle."""
    journal, store, llm, _ = contexte
    await _peupler(store, "discord:610", [f"Joue à Apex Legends, partie {i}" for i in range(6)])
    _reponse_llm(llm, {"delete": [], "update": [], "questions": []})

    await journal.run_memory_cleanup()

    envoye = llm.complete.await_args.args[1][0]["content"]
    assert "0. [" in envoye and "Apex Legends, partie 0" in envoye
    assert "5. [" in envoye
