# tests/test_journal_refuse_le_fallback.py
"""Le message d'excuse du LLM n'est pas une entrée de journal.

`llm.complete()` ne lève pas : il retourne FALLBACK_RESPONSE. Sans garde, ce
texte était publié dans le salon, archivé, puis réinjecté le lendemain comme
« ton journal d'hier » et intégré à la synthèse narrative.
Constaté en prod : 15 entrées de `journal_archive` du 2026-05-16 au 2026-06-02,
`word_count=10`, toutes identiques au message d'erreur.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.llm import FALLBACK_RESPONSE
from bot.intelligence.journal import DailyJournal


def _make(primaire: str, secondaire: str = "brouillon relu"):
    config = MagicMock()
    config.bot.journal_channel_id = 12345
    config.bot.journal_time = "03:00"
    config.bot.emotion_peak_threshold = 0.7
    config.bot.name = "Wally"

    llm = MagicMock()
    llm.complete = AsyncMock(return_value=primaire)
    llm_secondary = MagicMock()
    llm_secondary.complete = AsyncMock(return_value=secondaire)

    emotion = MagicMock()
    emotion.get_state = MagicMock(
        return_value={"anger": 0.1, "joy": 0.5, "sadness": 0.0, "curiosity": 0.3, "boredom": 0.0}
    )
    memory = MagicMock()
    memory.get_all_contexts = MagicMock(return_value=[
        {"author": "Alice", "content": "Hello", "timestamp": 1000.0},
    ])

    db = MagicMock()
    db.insert_journal = AsyncMock()

    j = DailyJournal(config, llm, llm_secondary, emotion, memory, db=db)
    envoyes: list[str] = []
    j.set_send_callback(AsyncMock(side_effect=lambda text, **kw: envoyes.append(text)))
    return j, db, envoyes


@pytest.mark.asyncio
async def test_le_fallback_n_est_ni_publie_ni_archive():
    j, db, envoyes = _make(FALLBACK_RESPONSE, secondaire=FALLBACK_RESPONSE)
    await j.generate_and_send()
    assert envoyes == []
    db.insert_journal.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_fallback_du_primaire_ne_survit_pas_au_pass_de_voix():
    """Le pass de voix travaille sur un brouillon qui est déjà un message d'erreur."""
    j, db, envoyes = _make(FALLBACK_RESPONSE, secondaire="un joli texte inventé sur du vide")
    await j.generate_and_send()
    assert envoyes == []
    db.insert_journal.assert_not_awaited()


@pytest.mark.asyncio
async def test_une_vraie_entree_passe_toujours():
    j, db, envoyes = _make("Trois raids aujourd'hui, et personne pour relever.")
    await j.generate_and_send()
    assert len(envoyes) == 1
    db.insert_journal.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_texte_vide_est_traite_comme_un_echec():
    j, db, envoyes = _make("   ", secondaire="   ")
    await j.generate_and_send()
    assert envoyes == []
    db.insert_journal.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_resume_de_contexte_ne_retient_pas_le_fallback():
    """Un chunk résumé en échec ne doit pas entrer dans le contexte du journal."""
    j, _, _ = _make("peu importe")
    j._llm_secondary.complete = AsyncMock(return_value=FALLBACK_RESPONSE)

    gros = [{"author": "a", "content": "x" * 400} for _ in range(120)]
    out = await j._build_context_text(gros)

    assert FALLBACK_RESPONSE not in (out or "")
