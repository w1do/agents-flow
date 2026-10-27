import asyncio

from app.models import TaskEvent
from app.repositories.task_history import TaskHistory


async def test_old_plan_button_after_new_revision_is_rejected(telegram):
    task = telegram.flow.task("backlog")
    old = telegram.callback(task, "plan", "approved")
    TaskHistory(telegram.flow.session).append(task.id, "plan", "New plan")
    telegram.flow.session.commit()
    await telegram.post(old)
    telegram.flow.session.refresh(task)
    assert task.status == "backlog"
    assert telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="plan_decision").count() == 0


async def test_old_publish_button_after_result_revision_is_rejected(telegram):
    task = telegram.flow.task("ready", leased=True)
    old = telegram.callback(task, "result", "publish")
    rework = telegram.callback(task, "result", "rework")
    await telegram.post(rework)
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    await telegram.post(telegram.message(text="Needs changes", reply=prompt))
    TaskHistory(telegram.flow.session).append(task.id, "result", "Changed result")
    telegram.flow.session.commit()
    await telegram.post(old)
    telegram.flow.session.refresh(task)
    assert task.status == "active"
    assert telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="result_decision").count() == 1


async def test_same_button_callback_is_one_shot(telegram):
    task = telegram.flow.task("ready", leased=True)
    first = telegram.callback(task, "result", "keep_ready")
    second = telegram.callback(task, "result", "keep_ready")
    first["callback_query"]["data"] = second["callback_query"]["data"]
    await asyncio.gather(telegram.post(first), telegram.post(second))
    telegram.runtime.actions.cache.items.clear()
    third = telegram.callback(task, "result", "keep_ready")
    third["callback_query"]["data"] = second["callback_query"]["data"]
    await telegram.post(third)
    assert telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="result_decision").count() == 1


async def test_decision_409_rolls_back_without_event(telegram, monkeypatch):
    from fastapi import HTTPException
    from app.services import decisions

    task = telegram.flow.task("ready", leased=True)
    update = telegram.callback(task, "result", "publish")
    original = decisions.decide

    def conflict_after_mutation(*args):
        original(*args)
        raise HTTPException(409)

    monkeypatch.setattr(decisions, "decide", conflict_after_mutation)
    await telegram.post(update)
    telegram.flow.session.refresh(task)
    assert task.status == "ready"
    assert telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="result_decision").count() == 0


async def test_old_feedback_after_panel_keep_ready_is_rejected(telegram):
    task = telegram.flow.task("ready", leased=True)
    await telegram.post(telegram.callback(task, "result", "rework"))
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    response = await telegram.flow.send("POST", f"/tasks/{task.id}/result/decision",
                                        {"decision": "keep_ready"})
    assert response.status_code == 200
    await telegram.post(telegram.message(text="Old feedback", reply=prompt))
    telegram.flow.session.refresh(task)
    decisions = telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="result_decision").all()
    assert task.status == "ready" and len(decisions) == 1
    assert decisions[0].payload["decision"] == "keep_ready"


async def test_feedback_reply_is_consumed_once(telegram):
    task = telegram.flow.task("ready", leased=True)
    await telegram.post(telegram.callback(task, "result", "rework"))
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    reply = telegram.message(text="Change this", reply=prompt)
    await telegram.post(reply)
    reply["update_id"] += 100
    await telegram.post(reply)
    events = telegram.flow.session.query(TaskEvent).filter_by(task_id=task.id,
        event_type="result_decision").all()
    assert len(events) == 1 and events[0].payload["feedback"] == "Change this"


async def test_feedback_prompt_failure_releases_action(telegram):
    task = telegram.flow.task("backlog")
    update = telegram.callback(task, "plan", "rejected")
    telegram.fake.send_error = RuntimeError("offline")
    await telegram.post(update)
    telegram.fake.send_error = None
    update["update_id"] += 100
    await telegram.post(update)
    assert any(row["text"] == "Ответьте на это сообщение с замечанием." for row in telegram.fake.messages)


async def test_callback_network_wait_has_no_open_session(telegram, monkeypatch):
    task = telegram.flow.task("backlog")
    update = telegram.callback(task, "plan", "rejected")
    original = telegram.fake.send_message
    entered, resume = asyncio.Event(), asyncio.Event()

    async def checked_send(*args, **kwargs):
        assert not telegram.flow.session.in_transaction()
        if args[1] == "Ответьте на это сообщение с замечанием.":
            entered.set()
            await resume.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(telegram.fake, "send_message", checked_send)
    first = asyncio.create_task(telegram.post(update))
    await asyncio.wait_for(entered.wait(), 2)
    second = await telegram.post(telegram.message(text="A second request during Telegram wait"))
    assert second.status_code == 200
    resume.set()
    assert (await first).status_code == 200


async def test_feedback_secrets_are_redacted(telegram):
    from sqlalchemy import select

    task = telegram.flow.task("backlog")
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    prompt = next(row["message_id"] for row in telegram.fake.messages
                  if row["text"] == "Ответьте на это сообщение с замечанием.")
    text = "Keep this note 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef and sk-abcdefghijklmnopqrstuvwxyz123456"
    await telegram.post(telegram.message(text=text, reply=prompt))
    assert "Keep this note" in task.plan_feedback
    assert "123456:" not in task.plan_feedback and "sk-" not in task.plan_feedback
    event = telegram.flow.session.scalar(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.event_type == "plan_decision"))
    assert "Keep this note" in event.payload["feedback"]
    assert "123456:" not in event.payload["feedback"] and "sk-" not in event.payload["feedback"]
