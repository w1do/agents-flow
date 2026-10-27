import asyncio
from threading import Event
import time as wall_time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.api.agent_claim_limit import claim_limiter
from app.models import TaskEvent
from app.repositories.project import ProjectRepository
from app.services.lease_expiry import expire_due
from app.services import lease_expiry
from app.core import time


@pytest.mark.parametrize("source,target,status", [
    ("backlog", "planning", 403), ("backlog", "merged", 409),
    ("ready", "active", 403), ("ready", "merged", 403),
    ("active", "stalled", 403), ("active", "merged", 409),
    ("active", "paused", 403), ("active", "trash", 403),
    ("active", "error", 403),
])
async def test_agent_status_matrix_through_events_api(flow, source, target, status):
    task = flow.task(source, leased=True)
    response = await flow.report(task, "events", {
        "event_type": "progress", "message": "Status update", "payload": {"status": target},
    })
    assert response.status_code == status
    flow.session.refresh(task)
    assert task.status == source


@pytest.mark.parametrize("event_type", [
    "publication-result", "decision", "lease-expired", "status-changed", "result_decision",
])
async def test_agent_cannot_submit_server_event_types(flow, event_type):
    task = flow.task("active", leased=True)
    response = await flow.report(task, "events", {"event_type": event_type, "message": "Fake"})
    assert response.status_code == 403


async def test_fake_publication_result_cannot_suppress_publish(flow):
    task = flow.task("ready", leased=True)
    await flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "publish"})
    fake = await flow.report(task, "events", {
        "event_type": "publication-result", "message": "Fake publication",
    })
    assert fake.status_code == 403
    state = await flow.state(task)
    assert state.json()["publication_requested"] is True


async def test_report_secrets_are_removed_from_database_and_task_card(flow):
    token = "ghp_" + "A" * 36
    task = flow.task("active", leased=True)
    response = await flow.report(task, "events", {
        "event_type": "progress", "message": f"Using {token}",
        "payload": {"nested": {"value": token}}, "checkpoint": {"text": token},
    })
    assert response.status_code == 200
    card = await flow.send("GET", f"/tasks/{task.id}")
    assert token not in card.text
    event = flow.session.scalar(select(TaskEvent).where(TaskEvent.task_id == task.id))
    assert token not in event.message and token not in str(event.payload)
    flow.session.refresh(task)
    assert token not in str(task.checkpoint)


async def test_expired_merged_lease_is_released_and_task_stays_merged(flow, clock):
    task = flow.task("merged", leased=True)
    task.lease_expires_at = clock[0] + timedelta(seconds=1)
    flow.session.commit()
    clock[0] += timedelta(seconds=2)
    expire_due(flow.session)
    flow.task()
    assert (await flow.claim()).status_code == 200
    flow.session.refresh(task)
    assert task.status == "merged" and task.lease_id is None


async def test_claim_rate_limit_returns_retry_after(flow, monkeypatch):
    monkeypatch.setattr(claim_limiter, "attempts", 1)
    flow.task()
    assert (await flow.claim()).status_code == 200
    limited = await flow.claim()
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


async def test_execution_state_hides_another_project_task(flow):
    foreign_project = ProjectRepository(flow.session).create(name="Other")
    task = flow.task("active", leased=True)
    foreign_agent, headers = flow.make_agent("Foreign", foreign_project.id)
    response = await flow.send("GET", f"/tasks/{task.id}/execution-state?lease_id={task.lease_id}",
                               headers=headers)
    assert response.status_code == 404


async def test_expiry_monitor_does_not_block_event_loop(monkeypatch):
    worker_started = Event()

    def blocking_expiry():
        worker_started.set()
        wall_time.sleep(0.05)

    monkeypatch.setattr(lease_expiry, "_expire_once", blocking_expiry)
    task = asyncio.create_task(lease_expiry.run_expiry_in_thread())
    timer_start = wall_time.monotonic()
    await asyncio.sleep(0.02)
    assert wall_time.monotonic() - timer_start < 0.1
    assert worker_started.is_set()
    await task
    await asyncio.get_running_loop().shutdown_default_executor()
