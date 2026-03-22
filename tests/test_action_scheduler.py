"""Tests for ActionScheduler — SQLite persistence + apscheduler orchestration."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from bot.core.actions.scheduler import ActionScheduler

TZ = ZoneInfo("Europe/Paris")


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.insert_action_task = AsyncMock(return_value=1)
    db.update_action_task = AsyncMock()
    db.get_action_task = AsyncMock(return_value=None)
    db.get_active_action_tasks = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_executor():
    return AsyncMock()


@pytest.fixture
def mock_apscheduler():
    sched = MagicMock()
    sched.add_job = MagicMock(return_value=MagicMock(id="job_1"))
    sched.remove_job = MagicMock()
    sched.get_job = MagicMock(return_value=None)
    return sched


@pytest.fixture
def scheduler(mock_db, mock_executor, mock_apscheduler):
    return ActionScheduler(mock_db, mock_executor, mock_apscheduler)


@pytest.mark.asyncio
async def test_schedule_once_task(scheduler, mock_db):
    run_at = (datetime.now(TZ) + timedelta(hours=1)).isoformat()
    task_id = await scheduler.schedule(
        action_type="reminder", description="Buy bread",
        creator_id="123", creator_platform="discord",
        target_channel="456", target_platform="discord",
        payload='{"message": "Buy bread!"}',
        schedule_type="once", schedule_spec=f'{{"run_at": "{run_at}"}}',
        max_executions=1,
    )
    assert task_id == 1
    mock_db.insert_action_task.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_interval_task(scheduler, mock_db, mock_apscheduler):
    task_id = await scheduler.schedule(
        action_type="reminder", description="Drink water",
        creator_id="123", creator_platform="discord",
        target_channel="456", target_platform="discord",
        payload='{"message": "Drink water!"}',
        schedule_type="interval", schedule_spec='{"minutes": 30}',
        max_executions=None,
    )
    assert task_id == 1
    mock_apscheduler.add_job.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_task(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {"id": 1, "status": "active"}
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler.cancel(1)
    mock_db.update_action_task.assert_called_once()
    call_kwargs = mock_db.update_action_task.call_args
    assert call_kwargs[1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_pause_and_resume(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {"id": 1, "status": "active"}
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler.pause(1)
    assert mock_db.update_action_task.call_args[1]["status"] == "paused"

    mock_db.get_action_task.return_value = {"id": 1, "status": "paused",
        "schedule_type": "interval", "schedule_spec": '{"minutes": 30}',
        "action_type": "reminder", "payload": '{}',
        "target_channel": "456", "target_platform": "discord",
        "creator_id": "123", "creator_platform": "discord",
        "description": "test", "max_executions": None,
        "execution_count": 0, "consecutive_failures": 0,
        "last_error": None, "created_at": "", "updated_at": "",
        "next_run_at": None, "last_run_at": None}
    await scheduler.resume(1)
    assert mock_db.update_action_task.call_args[1]["status"] == "active"


@pytest.mark.asyncio
async def test_reload_marks_missed_once_tasks(scheduler, mock_db):
    past_time = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    mock_db.get_active_action_tasks.return_value = [
        {"id": 1, "schedule_type": "once", "next_run_at": past_time,
         "status": "active", "action_type": "reminder",
         "schedule_spec": f'{{"run_at": "{past_time}"}}',
         "payload": '{}', "target_channel": "456",
         "target_platform": "discord", "creator_id": "123",
         "creator_platform": "discord", "description": "test",
         "max_executions": 1, "execution_count": 0,
         "consecutive_failures": 0, "last_error": None,
         "created_at": "", "updated_at": "", "last_run_at": None},
    ]
    await scheduler.reload_all()
    mock_db.update_action_task.assert_called_once()
    assert mock_db.update_action_task.call_args[1]["status"] == "missed"


@pytest.mark.asyncio
async def test_reload_reschedules_recurring_tasks(scheduler, mock_db, mock_apscheduler):
    past_time = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
    mock_db.get_active_action_tasks.return_value = [
        {"id": 2, "schedule_type": "interval", "next_run_at": past_time,
         "status": "active", "action_type": "reminder",
         "schedule_spec": '{"minutes": 30}',
         "payload": '{}', "target_channel": "456",
         "target_platform": "discord", "creator_id": "123",
         "creator_platform": "discord", "description": "test",
         "max_executions": None, "execution_count": 5,
         "consecutive_failures": 0, "last_error": None,
         "created_at": "", "updated_at": "", "last_run_at": None},
    ]
    await scheduler.reload_all()
    mock_apscheduler.add_job.assert_called_once()
    for call in mock_db.update_action_task.call_args_list:
        assert call[1].get("status") != "missed"


@pytest.mark.asyncio
async def test_on_job_complete_increments_count(scheduler, mock_db):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 2, "max_executions": 10,
        "consecutive_failures": 0, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    await scheduler._on_job_executed(1, "Reminder sent!")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["execution_count"] == 3
    assert call_kwargs["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_on_job_complete_auto_completes_at_max(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 9, "max_executions": 10,
        "consecutive_failures": 0, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_executed(1, "Done")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_on_job_failure_once_task_marks_missed(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 0, "max_executions": 1,
        "consecutive_failures": 0, "schedule_type": "once",
        "schedule_spec": '{"run_at": "2026-03-23T18:00:00"}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_failed(1, "API down")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "missed"


@pytest.mark.asyncio
async def test_on_job_failure_auto_pauses_after_3(scheduler, mock_db, mock_apscheduler):
    mock_db.get_action_task.return_value = {
        "id": 1, "execution_count": 5, "max_executions": None,
        "consecutive_failures": 2, "schedule_type": "interval",
        "schedule_spec": '{"minutes": 30}', "status": "active",
    }
    mock_apscheduler.get_job.return_value = MagicMock()
    await scheduler._on_job_failed(1, "Connection refused")
    call_kwargs = mock_db.update_action_task.call_args[1]
    assert call_kwargs["status"] == "paused"
    assert call_kwargs["consecutive_failures"] == 3
    assert "Connection refused" in call_kwargs["last_error"]
