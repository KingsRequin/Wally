"""Un fait dont le sujet nomme quelqu'un d'autre va chez cette personne.

Constaté en prod : onze faits « Cluth joue à Valorant », « Cluth utilise un
tracker de performance »… rangés dans la mémoire de KingsRequin. Le triplet
disait pourtant `subject = "Cluth"`. Le LLM avait renvoyé `target_user_id` =
KingsRequin — probablement parce que c'est lui qui parlait — et le code prenait
cet identifiant au mot sans jamais le confronter au sujet du fait.

Conséquence : Wally lisait sur KingsRequin des choses vraies de quelqu'un
d'autre, et le ménage nocturne voyait des « doublons » entre deux personnes.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.db.schema_v2 import create_v2_tables
from bot.intelligence.fact_extractor import FactExtractor
from bot.intelligence.memory.facts import SQLiteFactStore


@pytest.fixture
async def contexte(tmp_path):
    chemin = str(tmp_path / "facts.db")
    await create_v2_tables(chemin)

    memory = MagicMock()
    memory.add = AsyncMock()
    memory.fact_store = SQLiteFactStore(chemin)
    memory._user_id = lambda plateforme, uid: f"{plateforme}:{uid}"

    llm = AsyncMock()
    db = AsyncMock()
    db.list_aliases = AsyncMock(return_value=[])
    db.list_memory_users = AsyncMock(return_value=[
        {"user_id": "discord:973", "username": "Cluth"},
        {"user_id": "discord:610", "username": "KingsRequin"},
        {"user_id": "twitch:751", "username": "cluthfps"},
        {"user_id": "discord:174", "username": "Jubeii"},
        {"user_id": "twitch:96", "username": "jubeii1979"},
    ])
    # twitch:751 et twitch:96 sont les comptes Twitch de personnes dont la
    # mémoire vit sur leur fiche Discord.
    db.get_alias_map = AsyncMock(return_value={
        "twitch:751": "discord:973",
        "twitch:96": "discord:174",
    })
    db.upsert_alias = AsyncMock()

    extracteur = FactExtractor(MagicMock(), memory, llm, db)
    ranges: list[tuple[str, str, str]] = []

    async def _capture(platform, raw_id, item, text, cat, disp, origin=None, expires_at=None):
        ranges.append((platform, raw_id, text))
        return True

    extracteur._store_fact = _capture
    return extracteur, llm, ranges


def _reponse(llm, subject: str, target: str, texte: str) -> None:
    llm.complete_structured = AsyncMock(return_value={
        "facts": [{
            "target_user_id": target,
            "facts": [{
                "text": texte, "category": "FAIT",
                "subject": subject, "predicate": "plays", "object": "Valorant",
            }],
        }],
        "aliases": [],
    })


def _messages(auteur_uid: str, nom: str, contenu: str) -> list[dict]:
    return [{"user_id": auteur_uid, "display_name": nom,
             "content": contenu, "timestamp": 1000.0}]


async def test_un_fait_sur_un_tiers_va_chez_le_tiers(contexte):
    extracteur, llm, ranges = contexte
    _reponse(llm, "Cluth", "discord:610", "Cluth joue à Valorant")

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "Cluth est vraiment bon à Valorant"),
        "discord", "canal-1",
    )

    assert ranges == [("discord", "973", "Cluth joue à Valorant")]


async def test_un_fait_sur_soi_reste_chez_soi(contexte):
    extracteur, llm, ranges = contexte
    _reponse(llm, "KingsRequin", "discord:610", "KingsRequin joue à Valorant")

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "je joue pas mal à Valorant en ce moment"),
        "discord", "canal-1",
    )

    assert ranges == [("discord", "610", "KingsRequin joue à Valorant")]


async def test_un_sujet_inconnu_ne_deplace_rien(contexte):
    """Sans correspondance certaine, on ne touche pas à l'attribution du LLM."""
    extracteur, llm, ranges = contexte
    _reponse(llm, "Bartholomew", "discord:610", "Bartholomew joue à Valorant")

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "Bartholomew joue à Valorant je crois"),
        "discord", "canal-1",
    )

    assert ranges == [("discord", "610", "Bartholomew joue à Valorant")]


async def test_le_pseudo_dune_autre_plateforme_va_au_compte_canonique(contexte):
    """« cluthfps » est le compte Twitch de Cluth. Le fait doit atterrir sur sa
    fiche Discord — la canonique — et pas sur la fiche Twitch, sinon on éparpille
    la mémoire d'une personne sur deux fiches au lieu de la rassembler."""
    extracteur, llm, ranges = contexte
    _reponse(llm, "cluthfps", "discord:610", "cluthfps joue à Valorant")

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "cluthfps enchaîne les ranked"),
        "discord", "canal-1",
    )

    assert ranges == [("discord", "973", "cluthfps joue à Valorant")]


async def test_un_fait_reste_chez_soi_quand_le_pseudo_est_lautre_compte(contexte):
    """Piège inverse : Jubeii parle de lui en se nommant par son pseudo Twitch.
    Ses souvenirs vivent sur sa fiche Discord ; les déplacer vers sa fiche Twitch
    couperait sa mémoire en deux."""
    extracteur, llm, ranges = contexte
    _reponse(llm, "jubeii1979", "discord:174", "jubeii1979 joue à Darktide")

    await extracteur._extract_facts(
        _messages("174", "Jubeii", "je joue à Darktide ce soir"), "discord", "canal-1",
    )

    assert ranges == [("discord", "174", "jubeii1979 joue à Darktide")]


async def test_la_casse_et_les_accents_ne_bloquent_pas(contexte):
    extracteur, llm, ranges = contexte
    _reponse(llm, "  CLUTH  ", "discord:610", "CLUTH joue à Valorant")

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "CLUTH joue encore"), "discord", "canal-1",
    )

    assert ranges[0][1] == "973"


async def test_sans_sujet_lattribution_du_llm_est_gardee(contexte):
    extracteur, llm, ranges = contexte
    llm.complete_structured = AsyncMock(return_value={
        "facts": [{
            "target_user_id": "discord:610",
            "facts": [{"text": "Aime le café", "category": "FAIT"}],
        }],
        "aliases": [],
    })

    await extracteur._extract_facts(
        _messages("610", "KingsRequin", "j'adore le café le matin"), "discord", "canal-1",
    )

    assert ranges == [("discord", "610", "Aime le café")]
