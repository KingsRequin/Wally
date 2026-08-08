"""`list_action_tasks` doit rendre des `dict`, pas des `sqlite3.Row`.

Le mixin annonce `-> list[dict]` mais renvoyait le résultat brut de
`fetch_all`, c'est-à-dire des `sqlite3.Row` : ça s'indexe, mais ça n'a pas de
`.get()`. `ActionService.list()` en appelait trois, donc l'outil LLM
`list_action_tasks` levait une `AttributeError` dès qu'UNE tâche existait — sur
Discord, Twitch et en vocal.

La panne était muette : la boucle de tool-calling avale l'exception et rend
« Tool error » au modèle, qui improvise une réponse. Et le test existant la
masquait en mockant la DB avec des `dict` — la forme que le code attendait, pas
celle qu'il recevait. On passe donc ici par une VRAIE base.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.db.database import Database


@pytest.fixture
async def db(tmp_path):
    base = await Database.create(str(tmp_path / "wally.db"))
    yield base
    await base.close()


async def _creer_tache(db: Database) -> int:
    return await db.insert_action_task(
        action_type="reminder",
        description="rappeler la review",
        creator_id="610",
        creator_platform="discord",
        target_channel="42",
        target_platform="discord",
        payload="{}",
        schedule_type="once",
        schedule_spec="{}",
        max_executions=1,
        status="active",
        created_at="2026-08-08T10:00:00",
        updated_at="2026-08-08T10:00:00",
        next_run_at="2026-08-09T10:00:00",
    )


async def test_les_lignes_rendues_sont_des_dicts(db):
    await _creer_tache(db)
    rows = await db.list_action_tasks()

    assert len(rows) == 1
    assert isinstance(rows[0], dict)
    # Le geste exact qui explosait.
    assert rows[0].get("next_run_at", None) is None or True
    assert rows[0].get("execution_count", 0) == 0


async def test_l_outil_list_action_tasks_repond_sur_une_vraie_base(db):
    """Le bout du chemin : ce que le modèle reçoit réellement."""
    from bot.intelligence.actions.service import ActionService

    await _creer_tache(db)
    service = ActionService(registry=MagicMock(), scheduler=MagicMock(), db=db)

    out = await service.list_tasks(user_id="610", platform="discord", user_roles=["admin"])

    assert out["status"] == "ok"
    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["description"] == "rappeler la review"
    assert out["tasks"][0]["execution_count"] == 0
