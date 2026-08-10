# tests/test_audit2_phaseN1_pertes.py
"""Phase N1 du second audit : décisions inversées et pertes de données.

A2-gate  — la décision du gate n'était pas validée contre son propre enum :
           « ignore » en minuscules et Wally RÉPOND, pendant que le journal
           écrit qu'il s'est tu.
A2-idx   — `True` passait pour un index : `facts[True]` réécrivait le DEUXIÈME
           souvenir du lot.
A2-json  — un champ non sérialisable emportait un lot de 200 événements de log.
A2-doubt — `doubt()` n'actualisait pas `last_seen_at` : le fait était archivé
           avant qu'on ait pu lever le doute.
A2-chart — le rendu du graphe pouvait faire perdre toute la journée de journal.
"""
import inspect
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────────── A2-gate ──────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("rendu,attendu", [
    ("ignore", "IGNORE"),          # casse basse : traversait avant
    ("  DEFER ", "DEFER"),
    ("RESPOND", "RESPOND"),
    ("n'importe quoi", "RESPOND"),  # hors enum → repli sûr
    (None, "RESPOND"),
])
async def test_la_decision_du_gate_est_normalisee_et_bornee(rendu, attendu):
    from bot.intelligence.gate import ResponseGate

    g = ResponseGate.__new__(ResponseGate)
    g._system = "sys"
    g._fact_store = MagicMock()
    g._fact_store.add = AsyncMock()
    g._llm = MagicMock()
    g._llm.complete_structured = AsyncMock(return_value={"decision": rendu})

    with patch("bot.intelligence.gate.bot_name", return_value="Wally"):
        d = await g.decide(
            message_content="salut", author_user_id="discord:1",
            emotion_state={"joy": 0.2}, relationship_facts=[], active_desires=[],
        )
    assert d.decision == attendu


# ────────────────────────────── A2-idx ──────────────────────────────
def test_un_booleen_nest_pas_un_index():
    from bot.intelligence.journal import _entier

    assert _entier(True) is False
    assert _entier(False) is False
    assert _entier(1) is True


def test_le_chemin_de_reformulation_utilise_la_meme_garde_que_la_suppression():
    from bot.intelligence.journal import DailyJournal

    src = inspect.getsource(DailyJournal._apply_cleanup_verdict)
    assert "if not _entier(idx) or not 0 <= idx < len(facts)" in src
    # La ligne de CODE, pas le commentaire qui explique pourquoi elle existe.
    assert "if not isinstance(idx, int) or not 0" not in src


# ────────────────────────────── A2-json ──────────────────────────────
def test_un_champ_non_serialisable_nemporte_pas_le_lot(tmp_path):
    from bot.core.conversation_log import ConversationLogger

    log = ConversationLogger.__new__(ConversationLogger)
    log._root = tmp_path

    class _Opaque:
        def __repr__(self):
            return "<objet discord>"

    lot = [
        ("discord", "salon", {"ts": 1_700_000_000.0, "type": "a", "x": _Opaque()}),
        ("discord", "salon", {"ts": 1_700_000_001.0, "type": "b"}),
    ]
    log._flush(lot)                     # ne doit pas lever

    ecrits = list(tmp_path.rglob("*.jsonl"))
    assert ecrits, "le lot entier a été perdu"
    lignes = ecrits[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lignes) == 2
    assert json.loads(lignes[0])["x"] == "<objet discord>"


# ────────────────────────────── A2-doubt ──────────────────────────────
def test_douter_dun_fait_lui_redonne_son_sursis():
    from bot.intelligence.memory.facts import SQLiteFactStore

    src = inspect.getsource(SQLiteFactStore.doubt)
    assert "last_seen_at = ?" in src
    assert "datetime.utcnow().isoformat()" in src


def test_le_menage_archive_bien_sur_last_seen_at():
    """La raison du correctif : c'est ce champ que le ménage regarde."""
    from bot.intelligence.memory.facts import SQLiteFactStore

    src = inspect.getsource(SQLiteFactStore.archive_stale_doubts)
    assert "last_seen_at <= ?" in src


# ────────────────────────────── A2-chart ──────────────────────────────
def test_un_graphe_en_echec_ne_fait_pas_perdre_le_journal():
    from bot.intelligence.journal import DailyJournal

    src = inspect.getsource(DailyJournal.generate_and_send)
    i = src.index("_generate_emotion_chart")
    bloc = src[max(0, i - 400):i + 300]
    assert "try:" in bloc
    assert "graphe des émotions non rendu" in bloc
