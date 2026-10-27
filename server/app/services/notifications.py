"""Translate committed task-service events into compact Telegram messages."""
from app.integrations.telegram.formatting import keyboard, message


def build(task, project, event, settings):
    if not project.telegram_chat_id:
        return None
    kind, payload = event.event_type, event.payload or {}
    markup, content = None, ""
    if kind == "created":
        heading, content = "Задача создана", task.source_text
    elif kind == "plan":
        heading, content = "План готов. Выберите действие.", task.plan_text
        markup = keyboard("plan", task.id, event.id)
    elif kind == "plan_decision":
        heading = {"approved": "Работа началась", "rejected": "План отправлен на улучшение",
                   "trash": "Задача отклонена"}.get(payload.get("decision"), "Решение сохранено")
    elif kind == "result":
        heading, content = "Результат готов. Нужна приёмка.", task.result_summary
        markup = keyboard("result", task.id, event.id)
    elif kind == "result_decision":
        heading = {"publish": "Результат принят. Начинается публикация.",
                   "rework": "Результат отправлен на доработку. Работа началась.",
                   "keep_ready": "Результат принят без публикации."}.get(
                       payload.get("decision"), "Решение сохранено")
        if payload.get("decision") == "keep_ready":
            markup = keyboard("result", task.id, event.id)
    elif kind == "publication-result":
        heading = ("Публикация завершена" if payload.get("success")
                   else "Публикация не удалась. Проверьте отчёт в панели.")
    elif kind in {"fail", "lease_expired"}:
        heading = "Работа остановлена. Проверьте задачу в панели и повторите запуск."
    else:
        return None
    return (project.telegram_chat_id, message(heading, content, task.id, settings), markup)
