import pytest

from app.integrations.telegram.formatting import MESSAGE_LIMIT, keyboard, units


def test_callback_data_fits_bot_limit_and_is_unique():
    from uuid import uuid4

    for kind in ("plan", "result"):
        rows = keyboard(kind, uuid4(), uuid4())["inline_keyboard"]
        values = [row[0]["callback_data"] for row in rows]
        assert all(len(value.encode("utf-8")) <= 64 for value in values)
        assert len(values) == len(set(values))


async def test_rest_creation_plan_start_result_acceptance_publication(telegram):
    flow = telegram.flow
    response = await flow.send("POST", f"/projects/{flow.project.id}/tasks", {
        "title": "Page", "description": "Build", "source_type": "api", "source_text": "Build a page",
    })
    assert response.status_code == 201
    await telegram.drain()
    assert "Задача создана" in telegram.fake.messages[-1]["text"]
    task = flow.task("planning", leased=True)
    assert (await flow.report(task, "plan", {"plan_text": "Step one"})).status_code == 200
    await telegram.drain()
    notice = telegram.fake.messages[-1]
    assert "План готов" in notice["text"] and "Step one" in notice["text"]
    assert [row[0]["text"] for row in notice["reply_markup"]["inline_keyboard"]] == [
        "Приступай", "Улучши план", "Отклонить",
    ]
    response = await flow.send("POST", f"/tasks/{task.id}/plan/decision", {"decision": "approved"})
    assert response.status_code == 200
    await telegram.drain()
    assert "Работа началась" in telegram.fake.messages[-1]["text"]
    assert (await flow.report(task, "events", {"event_type": "testing", "message": "Tests"})).status_code == 200
    assert (await flow.report(task, "result", {"result_summary": "Done", "result_data": {}})).status_code == 200
    await telegram.drain()
    notice = telegram.fake.messages[-1]
    assert "Нужна приёмка" in notice["text"] and "Done" in notice["text"]
    assert [row[0]["text"] for row in notice["reply_markup"]["inline_keyboard"]] == [
        "Принять и опубликовать", "Доработать", "Оставить без публикации",
    ]
    response = await flow.send("POST", f"/tasks/{task.id}/result/decision", {"decision": "publish"})
    assert response.status_code == 200
    await telegram.drain()
    assert "Результат принят" in telegram.fake.messages[-1]["text"]
    assert (await flow.report(task, "publication-result", {"success": True, "message": "Pushed"})).status_code == 200
    await telegram.drain()
    assert "Публикация завершена" in telegram.fake.messages[-1]["text"]


async def test_long_unicode_report_is_truncated_with_panel_marker(telegram):
    task = telegram.flow.task("planning", leased=True)
    text = "Подробный план 😀 " * 900
    assert (await telegram.flow.report(task, "plan", {"plan_text": text})).status_code == 200
    await telegram.drain()
    notice = telegram.fake.messages[-1]["text"]
    assert units(notice) <= MESSAGE_LIMIT and "полный текст — в панели" in notice
    assert str(task.id) in notice
    card = (await telegram.flow.send("GET", f"/tasks/{task.id}")).json()
    assert card["plan_text"] == text.strip()


@pytest.mark.parametrize("kind,fields,expected", [
    ("fail", {"message": "Traceback (most recent call last): PRIVATE_TOKEN=secret"}, "Работа остановлена"),
    ("publication-result", {"success": False, "message": ".env PRIVATE_TOKEN=secret"}, "Публикация не удалась"),
])
async def test_error_and_publication_details_never_sent(telegram, kind, fields, expected):
    task = telegram.flow.task("merged" if kind == "publication-result" else "active", leased=True)
    assert (await telegram.flow.report(task, kind, fields)).status_code == 200
    await telegram.drain()
    notice = telegram.fake.messages[-1]["text"]
    assert expected in notice
    assert all(value not in notice for value in ("Traceback", ".env", "PRIVATE_TOKEN", "secret"))


@pytest.mark.parametrize("content", [".env\nANOTHER_VALUE=private-value", "DATABASE_PASSWORD=private-value",
                                     "Traceback (most recent call last): private-value"])
async def test_plan_configuration_and_tracebacks_hidden(telegram, content):
    task = telegram.flow.task("planning", leased=True)
    assert (await telegram.flow.report(task, "plan", {"plan_text": content})).status_code == 200
    await telegram.drain()
    assert "private-value" not in telegram.fake.messages[-1]["text"]


async def test_known_settings_secrets_never_sent(telegram):
    settings = telegram.runtime.settings
    secrets = [settings.telegram_bot_token.get_secret_value(), settings.jwt_secret.get_secret_value(),
               settings.telegram_webhook_secret.get_secret_value()]
    await telegram.post(telegram.message(text="Credentials: " + " ".join(secrets)))
    assert all(secret not in str(telegram.fake.messages) for secret in secrets)


async def test_notification_failure_does_not_break_rest_or_mcp(telegram, mcp, caplog):
    telegram.fake.send_error = RuntimeError("PRIVATE TRANSPORT TOKEN")
    task = telegram.flow.task("planning", leased=True)
    assert (await telegram.flow.report(task, "plan", {"plan_text": "Plan"})).status_code == 200
    other = telegram.flow.task("planning", leased=True)
    response = await mcp.call("agent_report_plan", other, {"plan_text": "Another plan"})
    assert response["status"] == "backlog"
    await telegram.drain()
    assert "telegram_send_failed" in caplog.text and "PRIVATE TRANSPORT TOKEN" not in caplog.text




async def test_mcp_report_notifies_once_on_replay(telegram, mcp):
    task = telegram.flow.task("planning", leased=True)
    fields = {"plan_text": "MCP plan"}
    first = await mcp.call("agent_report_plan", task, fields, event_id="mcp-telegram-plan")
    second = await mcp.call("agent_report_plan", task, fields, event_id="mcp-telegram-plan")
    assert first["status"] == second["status"] == "backlog"
    await telegram.drain()
    assert len(telegram.fake.messages) == 1 and "MCP plan" in telegram.fake.messages[0]["text"]


async def test_unbound_project_and_rolled_back_events_do_not_notify(telegram):
    from app.schemas.tasks import TaskCreate
    from app.services import tasks

    flow = telegram.flow
    tasks.create(flow.session, flow.project.id, TaskCreate(title="Rollback", description="Text",
                                                        source_type="api", source_text="Text"))
    flow.session.rollback()
    await telegram.drain()
    assert telegram.fake.messages == []
    flow.project.telegram_chat_id = None
    flow.session.commit()
    tasks.create(flow.session, flow.project.id, TaskCreate(title="No chat", description="Text",
                                                        source_type="api", source_text="Text"))
    flow.session.commit()
    await telegram.drain()
    assert telegram.fake.messages == []
