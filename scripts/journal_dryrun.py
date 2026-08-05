"""Dry-run du journal : régénère une entrée passée avec les prompts actuels.

Sert à juger un changement de prompt sur du vrai contexte, sans rien publier :
n'envoie rien sur Discord, n'archive rien, n'écrit aucun topic.

Usage : PYTHONPATH=. python3 scripts/journal_dryrun.py 2026-08-04
"""
import asyncio
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from bot.config import Config
from bot.core.llm.factory import create_llm_client
from bot.db.database import Database
from bot.intelligence.journal import DailyJournal


class _StubEmotion:
    def __init__(self, state):
        self._state = state

    def get_state(self):
        return self._state


class _StubMemory:
    _alias_cache: dict = {}  # noqa: RUF012 — stub de test

    def get_all_contexts(self):
        return []

    async def cleanup_expired_facts(self):
        return None


async def main() -> None:
    target = date.fromisoformat(sys.argv[1])
    cfg = Config.load()
    db = await Database.create("data/wally.db")

    # État émotionnel réel du jour visé (dernier snapshot avant minuit suivant)
    rows = await db.fetch_all(
        "SELECT * FROM emotion_history WHERE snapshot_at < ? ORDER BY snapshot_at DESC LIMIT 1",
        (int(target.strftime("%s")) + 86400,),
    )
    emotions = (
        {e: float(rows[0][e]) for e in ("anger", "joy", "sadness", "curiosity", "boredom")}
        if rows
        else {"anger": 0.1, "joy": 0.2, "sadness": 0.1, "curiosity": 0.3, "boredom": 0.6}
    )

    primary = create_llm_client(cfg.llm.primary, db)
    secondary = create_llm_client(cfg.llm.secondary, db)

    # NO_VOICE_PASS=1 → compare la sortie brute du modèle principal au texte repassé
    if os.getenv("NO_VOICE_PASS"):
        from bot.core.llm import FALLBACK_RESPONSE

        _orig_complete = secondary.complete

        async def _skip_voice_pass(system, messages, purpose="", **kwargs):
            if purpose == "journal_voice_pass":
                return FALLBACK_RESPONSE  # le journal garde alors le brouillon primaire
            return await _orig_complete(system, messages, purpose=purpose, **kwargs)

        secondary.complete = _skip_voice_pass

    journal = DailyJournal(cfg, primary, secondary, _StubEmotion(emotions), _StubMemory(), db)

    captured: list[str] = []

    async def fake_send(text, **_kw):
        captured.append(text)

    journal.set_send_callback(fake_send)
    # Neutralise l'effet de bord : pas d'écriture de topics en base
    async def _noop(*_a, **_kw):
        return None

    journal._form_topics = _noop

    await journal.generate_and_send(archive=False, target_date=target)

    print("\n" + "=" * 72)
    for chunk in captured:
        print(chunk)
    print("=" * 72)
    await db.close()


asyncio.run(main())
