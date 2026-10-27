import pytest

from app.integrations.telegram.formatting import ACTION_CODES
from app.models import TaskEvent
from app.integrations.telegram.buttons import FEEDBACK_PROMPT


@pytest.mark.parametrize("decision,target", [("publish", "merged"), ("rework", "active")])
async def test_keep_ready_issues_current_buttons_and_rejects_old_ones(telegram, decision, target):
    task = telegram.flow.task("ready", leased=True)
    old = telegram.callback(task, "result", decision)
    keep = telegram.callback(task, "result", "keep_ready")
    assert (await telegram.post(keep)).status_code == 200
    rows = telegram.fake.messages[-1]["reply_markup"]["inline_keyboard"]
    current = next(row[0]["callback_data"] for row in rows
                   if row[0]["callback_data"][1] == ACTION_CODES[decision])
    assert current != old["callback_query"]["data"] and len(current.encode()) <= 64
    assert (await telegram.post(old)).status_code == 200
    assert telegram.runtime.feedback.items == {}
    fresh = telegram.callback(task, "result", decision)
    fresh["callback_query"]["data"] = current
    assert (await telegram.post(fresh)).status_code == 200
    if decision == "rework":
        prompt = next(row["message_id"] for row in telegram.fake.messages if row["text"] == FEEDBACK_PROMPT)
        assert (await telegram.post(telegram.message(text="Improve", reply=prompt))).status_code == 200
    telegram.flow.session.refresh(task)
    assert task.status == target
    assert (await telegram.post(keep)).status_code == 200
    assert (await telegram.post(fresh)).status_code == 200
    events = telegram.flow.session.query(TaskEvent).filter_by(event_type="result_decision").all()
    assert [event.payload["decision"] for event in events] == ["keep_ready", decision]


async def test_panel_keep_ready_also_issues_current_buttons(telegram):
    task = telegram.flow.task("ready", leased=True)
    telegram.callback(task, "result", "publish")  # seed the result revision
    response = await telegram.flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "keep_ready"})
    assert response.status_code == 200
    await telegram.drain()
    rows = telegram.fake.messages[-1]["reply_markup"]["inline_keyboard"]
    fresh = telegram.callback(task, "result", "publish")
    fresh["callback_query"]["data"] = rows[0][0]["callback_data"]
    assert (await telegram.post(fresh)).status_code == 200
    telegram.flow.session.refresh(task)
    assert task.status == "merged"
