import pytest

from app.integrations.telegram.buttons import FEEDBACK_PROMPT
from app.models import TaskEvent


@pytest.mark.parametrize("kind,decision,status,target", [
    ("plan", "rejected", "backlog", "planning"), ("result", "rework", "ready", "active"),
])
async def test_evicted_feedback_allows_button_and_reply_again(telegram, kind, decision, status, target):
    telegram.runtime.feedback.cache.limit = 1
    first = telegram.flow.task(status, leased=True)
    second = telegram.flow.task(status, leased=True)
    await telegram.post(telegram.callback(first, kind, decision))
    old_prompt = next(row["message_id"] for row in telegram.fake.messages if row["text"] == FEEDBACK_PROMPT)
    await telegram.post(telegram.callback(second, kind, decision))
    await telegram.post(telegram.message(text="Evicted reply", reply=old_prompt))
    assert "Нажмите кнопку ещё раз" in telegram.fake.messages[-1]["text"]
    await telegram.post(telegram.callback(first, kind, decision))
    assert "Напишите замечание" in telegram.fake.answers[-1][1]
    new_prompt = [row["message_id"] for row in telegram.fake.messages if row["text"] == FEEDBACK_PROMPT][-1]
    assert new_prompt != old_prompt
    await telegram.post(telegram.message(text="Retry feedback", reply=new_prompt))
    telegram.flow.session.refresh(first)
    assert first.status == target
    events = telegram.flow.session.query(TaskEvent).filter_by(task_id=first.id, event_type=f"{kind}_decision").all()
    assert len(events) == 1 and events[0].payload["feedback"] == "Retry feedback"


async def test_expiring_old_feedback_preserves_new_button_reservation(telegram, monkeypatch):
    from app.integrations.telegram import state

    now = [0.0]
    monkeypatch.setattr(state, "monotonic", lambda: now[0])
    original = telegram.fake.send_message

    async def send(chat, text, markup=None):
        if text == FEEDBACK_PROMPT:
            now[0] += 30  # prompt lifetime starts after its button reservation
        return await original(chat, text, markup)

    monkeypatch.setattr(telegram.fake, "send_message", send)
    task = telegram.flow.task("backlog")
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    now[0] = 901  # button reservation expired, original feedback expires at 930
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    prompt = [row["message_id"] for row in telegram.fake.messages if row["text"] == FEEDBACK_PROMPT][-1]
    await telegram.post(telegram.callback(task, "plan", "rejected"))
    assert "Кнопка уже использована" in telegram.fake.answers[-1][1]
    await telegram.post(telegram.message(text="New reservation feedback", reply=prompt))
    telegram.flow.session.refresh(task)
    assert task.status == "planning" and task.plan_feedback == "New reservation feedback"
