import pytest

from telegram_helpers import CHAT, USER


@pytest.mark.parametrize("kind,decision,status,target", [
    ("plan", "approved", "backlog", "active"), ("plan", "rejected", "backlog", "planning"),
    ("plan", "trash", "backlog", "trash"), ("result", "publish", "ready", "merged"),
    ("result", "rework", "ready", "active"), ("result", "keep_ready", "ready", "ready"),
])
async def test_buttons_use_decision_service(telegram, kind, decision, status, target):
    flow = telegram.flow
    task = flow.task(status, leased=True)
    update = telegram.callback(task, kind, decision)
    assert (await telegram.post(update)).status_code == 200
    assert (await telegram.post(update)).status_code == 200
    if decision in {"rejected", "rework"}:
        flow.session.refresh(task)
        assert task.status == status
        prompt = next(row for row in telegram.fake.messages if row["reply_markup"])
        reply = telegram.message(text="Уточни проверку", reply=prompt["message_id"])
        assert (await telegram.post(reply)).status_code == 200
    flow.session.refresh(task)
    assert task.status == target
    card = (await flow.send("GET", f"/tasks/{task.id}")).json()
    events = [event for event in card["events"] if event["event_type"] == f"{kind}_decision"]
    assert len(events) == 1 and events[0]["payload"]["decision"] == decision
    if decision in {"rejected", "rework"}:
        assert events[0]["payload"]["feedback"] == "Уточни проверку"
    assert telegram.fake.answers


async def test_callback_cannot_decide_task_from_another_project(telegram):
    from app.repositories.project import ProjectRepository

    flow = telegram.flow
    other = ProjectRepository(flow.session).create(name="Other", telegram_chat_id="-67890")
    task = flow.task("backlog", project_id=other.id)
    assert (await telegram.post(telegram.callback(task, "plan", "approved"))).status_code == 200
    flow.session.refresh(task)
    assert task.status == "backlog" and "недоступна" in telegram.fake.answers[-1][1]


async def test_foreign_chat_and_invalid_or_stale_callback(telegram):
    task = telegram.flow.task("new")
    update = telegram.callback(task, "plan", "approved", chat="-999")
    assert (await telegram.post(update)).status_code == 200 and telegram.fake.answers == []
    assert (await telegram.post(telegram.callback(task, "plan", "approved"))).status_code == 200
    update = telegram.callback(task, "plan", "approved")
    update["callback_query"]["data"] = "p:publish:malformed"
    assert (await telegram.post(update)).status_code == 200
    telegram.flow.session.refresh(task)
    assert task.status == "new"


async def test_feedback_bound_to_user_and_prompt(telegram):
    task = telegram.flow.task("backlog")
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    await telegram.post(telegram.message(text="Wrong user", reply=prompt, user=USER + 1))
    telegram.flow.session.refresh(task)
    assert task.status == "backlog"
    await telegram.post(telegram.message(text="Correct user", reply=prompt))
    telegram.flow.session.refresh(task)
    assert task.status == "planning" and task.plan_feedback == "Correct user"


async def test_prompt_expires_without_creating_task(telegram, monkeypatch):
    from sqlalchemy import func, select
    from app.models import Task
    from app.integrations.telegram import state

    task = telegram.flow.task("backlog")
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    now = state.monotonic()
    monkeypatch.setattr(state, "monotonic", lambda: now + 901)
    await telegram.post(telegram.message(text="Late feedback", reply=prompt))
    telegram.flow.session.refresh(task)
    assert task.status == "backlog"
    assert telegram.flow.session.scalar(select(func.count()).select_from(Task)) == 1


