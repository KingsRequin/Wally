"""L'extraction ne doit pas re-proposer ce qui est déjà en mémoire.

Le fact_extractor vide son tampon à chaque flush — il ne relit donc jamais deux
fois les mêmes messages. Mais il repart de zéro tous les 5 messages : le prompt
reçoit les alias et la liste des utilisateurs connus, jamais les FAITS déjà
mémorisés sur les participants. Le modèle ré-extrait donc « joue à Valorant »
sans savoir que c'est en base depuis six semaines, avec une formulation
légèrement différente à chaque passage :

    18:07:36  A récemment récupéré sa connexion internet
    18:08:17  A eu des problèmes de connexion récemment
    18:08:58  A eu des problèmes de connexion récemment (récupérée mardi)
    18:09:45  Cluth a récemment récupéré sa connexion internet

Le ménage nocturne nettoie derrière ; ceci ferme le robinet.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.fact_extractor import FactExtractor
from bot.intelligence.memory.facts import AtomicFact, FactCategory, SQLiteFactStore


@pytest.fixture
async def contexte(tmp_path):
    chemin = str(tmp_path / "facts.db")
    await create_v2_tables(chemin)
    store = SQLiteFactStore(chemin)

    memory = MagicMock()
    memory.add = AsyncMock()
    memory.fact_store = store
    memory._user_id = lambda plateforme, uid: f"{plateforme}:{uid}"

    llm = AsyncMock()
    llm.complete_structured = AsyncMock(return_value={"facts": [], "aliases": []})

    db = AsyncMock()
    db.list_aliases = AsyncMock(return_value=[])
    db.list_memory_users = AsyncMock(return_value=[])

    return FactExtractor(MagicMock(), memory, llm, db), store, llm


async def _memoriser(store, uid: str, contenus: list[str]) -> None:
    for contenu in contenus:
        await store.add(
            AtomicFact(user_id=uid, content=contenu, category=FactCategory.FAIT)
        )


def _messages(*contenus: str, uid: str = "610", nom: str = "KingsRequin") -> list[dict]:
    return [
        {"user_id": uid, "display_name": nom, "content": c, "timestamp": 1000.0 + i}
        for i, c in enumerate(contenus)
    ]


def _prompt_envoye(llm) -> str:
    return llm.complete_structured.await_args.args[1][0]["content"]


# ── Ce que le modèle doit voir ───────────────────────────────────────────────

async def test_les_faits_deja_connus_sont_injectes(contexte):
    extracteur, store, llm = contexte
    await _memoriser(store, "discord:610", [
        "Joue à Valorant, classé Diamant 3",
        "Héberge Wally sur son serveur personnel",
    ])

    await extracteur._extract_facts(
        _messages("je viens de finir une ranked Valorant, encore une défaite"),
        "discord", "canal-1",
    )

    envoye = _prompt_envoye(llm)
    assert "Joue à Valorant, classé Diamant 3" in envoye


async def test_seuls_les_faits_en_rapport_remontent(contexte):
    """Injecter TOUS les souvenirs d'une personne à chaque flush coûterait des
    milliers de tokens toutes les 5 messages. Seuls ceux que la conversation
    risque de faire ré-extraire sont utiles."""
    extracteur, store, llm = contexte
    await _memoriser(store, "discord:610", [
        "Joue à Valorant, classé Diamant 3",
        "Possède une médiathèque Jellyfin avec 367 films",
    ])

    await extracteur._extract_facts(
        _messages("encore une ranked Valorant de perdue ce soir"),
        "discord", "canal-1",
    )

    envoye = _prompt_envoye(llm)
    assert "Valorant" in envoye
    assert "Jellyfin" not in envoye


async def test_sans_fait_connu_aucun_bloc_parasite(contexte):
    extracteur, _store, llm = contexte

    await extracteur._extract_facts(
        _messages("salut tout le monde, ça farm dur aujourd'hui"),
        "discord", "canal-1",
    )

    envoye = _prompt_envoye(llm)
    assert "Déjà en mémoire" not in envoye


async def test_chaque_participant_a_ses_propres_faits(contexte):
    """Scopé par personne : les souvenirs de l'un ne fuient pas chez l'autre."""
    extracteur, store, llm = contexte
    await _memoriser(store, "discord:610", ["KingsRequin joue à League of Legends"])
    await _memoriser(store, "discord:973", ["Cluth joue à Valorant en Diamant 3"])

    messages = [
        {"user_id": "610", "display_name": "KingsRequin",
         "content": "je relance une game de League ce soir", "timestamp": 1000.0},
        {"user_id": "973", "display_name": "Cluth",
         "content": "moi je repars sur Valorant en ranked", "timestamp": 1001.0},
    ]
    await extracteur._extract_facts(messages, "discord", "canal-1")

    envoye = _prompt_envoye(llm)
    assert "KingsRequin joue à League of Legends" in envoye
    assert "Cluth joue à Valorant en Diamant 3" in envoye


async def test_le_volume_injecte_est_borne(contexte):
    """Un salon Twitch actif peut aligner des dizaines de participants."""
    extracteur, store, llm = contexte
    await _memoriser(store, "discord:610", [
        f"Joue à Valorant en ranked, session numéro {i}" for i in range(40)
    ])

    await extracteur._extract_facts(
        _messages("encore une ranked Valorant ce soir"), "discord", "canal-1",
    )

    envoye = _prompt_envoye(llm)
    injectes = envoye.count("session numéro")
    assert 0 < injectes <= 8, f"{injectes} souvenirs injectés, plafond attendu 8"


async def test_la_consigne_de_ne_pas_repeter_accompagne_les_faits(contexte):
    """Montrer les faits sans dire quoi en faire, c'est inviter à les recopier."""
    extracteur, store, llm = contexte
    await _memoriser(store, "discord:610", ["Joue à Valorant, classé Diamant 3"])

    await extracteur._extract_facts(
        _messages("ma ranked Valorant s'est mal passée"), "discord", "canal-1",
    )

    envoye = _prompt_envoye(llm).lower()
    assert "déjà en mémoire" in envoye
    assert "ré-extrais" in envoye or "n'extrais pas" in envoye


# ── Robustesse ───────────────────────────────────────────────────────────────

async def test_une_recherche_en_panne_ne_bloque_pas_lextraction(contexte):
    extracteur, _store, llm = contexte
    extracteur._memory.fact_store = MagicMock()
    extracteur._memory.fact_store.search_fts = AsyncMock(
        side_effect=RuntimeError("FTS индекс cassé")
    )

    await extracteur._extract_facts(
        _messages("une phrase quelconque de conversation"), "discord", "canal-1",
    )

    llm.complete_structured.assert_awaited_once()


async def test_sans_store_lextraction_tourne_quand_meme(contexte):
    extracteur, _store, llm = contexte
    extracteur._memory.fact_store = None

    await extracteur._extract_facts(
        _messages("une phrase quelconque de conversation"), "discord", "canal-1",
    )

    llm.complete_structured.assert_awaited_once()
