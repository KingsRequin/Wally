# tests/test_audit2_phaseE_silences.py
"""Phase E du second audit : les silences, et le STT qui rendait sourd.

A2-9  — changer le provider STT à chaud cassait l'écoute pour toute la session.
A2-llm — `complete()` rendait "" sur le chemin Responses API, le SEUL emprunté ;
        deux appels DeepSeek contournaient le backoff ;
        `complete_with_reasoning` laissait passer le markup DSML.
A2-disc — sept `except Exception: pass` muets sur l'assemblage du contexte.
A2-idx — `get_due_facts` scannait les 14 391 faits à chaque tick.
"""
import inspect
import sqlite3
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.core.llm.base import FALLBACK_RESPONSE


# ────────────────────────────── A2-9 ──────────────────────────────
def _service(provider="faster_whisper"):
    from bot.discord.voice.service import VoiceService

    s = VoiceService.__new__(VoiceService)
    s._cfg = MagicMock(stt_provider=provider)
    s._bot = MagicMock()
    s._bot.config.bot.name = "Wally"
    s._bot.config.bot.trigger_names = []
    s._streaming = MagicMock()
    s._maintain_task = None
    s._vc = None
    s._tts = None
    s._build_stt_pipeline = MagicMock()
    s._detach_service = MagicMock()
    return s


def test_changer_de_provider_en_session_ne_touche_pas_au_pipeline():
    s = _service("faster_whisper")
    s._vc = MagicMock()                       # une session est en cours
    s.reload_config(MagicMock(stt_provider="remote_stream", azure_voice="v"))
    s._build_stt_pipeline.assert_not_called()


def test_changer_de_provider_hors_session_reconstruit_bien():
    s = _service("faster_whisper")
    s._vc = None                              # personne en vocal
    s.reload_config(MagicMock(stt_provider="remote_stream", azure_voice="v"))
    s._build_stt_pipeline.assert_called_once()


def test_les_autres_reglages_passent_toujours_a_chaud():
    s = _service("faster_whisper")
    s._vc = MagicMock()
    s.reload_config(MagicMock(stt_provider="faster_whisper", azure_voice="autre"))
    s._build_stt_pipeline.assert_called_once()


# ────────────────────────────── LLM ──────────────────────────────
@pytest.mark.asyncio
async def test_le_chemin_responses_respecte_le_contrat_sur_une_reponse_vide():
    from bot.core.llm.openai_client import OpenAILLMClient

    c = OpenAILLMClient.__new__(OpenAILLMClient)
    c._model = "gpt-5-nano"
    c._client = MagicMock()
    c._client.responses.create = AsyncMock(
        return_value=MagicMock(output_text="", usage=None)
    )
    c._log_cost = AsyncMock()
    c._max_tokens = 400
    c._temperature = 0.3
    c._reasoning_effort = "low"
    c._text_verbosity = None

    out = await c._complete_responses_api("sys", [{"role": "user", "content": "x"}], "test")
    assert out == FALLBACK_RESPONSE


def test_tous_les_appels_deepseek_passent_par_le_backoff():
    from bot.core.llm import deepseek

    src = inspect.getsource(deepseek)
    # Un seul appel direct subsiste : celui DANS `_creer_avec_reprises`.
    assert src.count("self._client.chat.completions.create") == 1


def test_le_raisonnement_est_nettoye_du_markup():
    from bot.core.llm.deepseek import DeepSeekLLMClient

    src = inspect.getsource(DeepSeekLLMClient.complete_with_reasoning)
    assert "_strip_dsml(msg.content or \"\")" in src


# ────────────────────────────── Discord ──────────────────────────────
def test_l_assemblage_du_contexte_ne_se_tait_plus():
    from bot.discord import handlers

    src = inspect.getsource(handlers)
    i = src.index("memory_parts")
    fin = src.index('situation: dict = {"platform": "Discord"}', i)
    bloc = src[i:fin]
    assert "except Exception:\n            pass" not in bloc, "silence restant"
    assert bloc.count("Mémoire : bloc «") >= 6


# ────────────────────────────── index ──────────────────────────────
def test_l_index_des_rappels_est_declare():
    src = Path("bot/db/schema_v2.py").read_text(encoding="utf-8")
    assert "idx_facts_scheduled" in src
    assert "WHERE scheduled_at IS NOT NULL" in src


def test_l_index_evite_le_scan_complet():
    """La preuve, exécutée : SCAN devient SEARCH."""
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE atomic_facts(id INTEGER PRIMARY KEY, scheduled_at TEXT, status TEXT)"
    )
    requete = (
        "EXPLAIN QUERY PLAN SELECT * FROM atomic_facts "
        "WHERE scheduled_at IS NOT NULL AND scheduled_at <= '2026-08-10' "
        "AND status = 'active' ORDER BY scheduled_at ASC"
    )
    avant = " ".join(str(r[-1]) for r in c.execute(requete))
    assert "SCAN" in avant

    c.execute(
        "CREATE INDEX idx_facts_scheduled ON atomic_facts(scheduled_at) "
        "WHERE scheduled_at IS NOT NULL"
    )
    apres = " ".join(str(r[-1]) for r in c.execute(requete))
    assert "SEARCH" in apres and "TEMP B-TREE" not in apres
