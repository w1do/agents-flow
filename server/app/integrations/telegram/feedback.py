from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select
import re

from app.models import Task
from app.schemas.reports import PlanDecisionRequest, ResultDecisionRequest
from app.services import decisions
from app.integrations.telegram.revisions import current

FEEDBACK_PROMPT = "Ответьте на это сообщение с замечанием."


async def feedback(session, runtime, project, message, outcome):
    reply = message.reply_to_message
    if reply is None:
        return False
    chat, user, prompt = str(message.chat.id), message.sender.id if message.sender else None, reply.message_id
    pending = runtime.feedback.get(chat, user, prompt)
    if pending is None and not (reply.sender and reply.sender.is_bot and reply.text == FEEDBACK_PROMPT):
        return False
    if pending is None or not message.text or not message.text.strip():
        await runtime.send(chat, "Замечание недоступно. Нажмите кнопку ещё раз и ответьте текстом.")
        return True
    task_id, kind, decision, revision, action = pending
    if not runtime.actions.cache.get(action):
        runtime.feedback.take(chat, user, prompt)
        await runtime.send(chat, "Замечание уже обработано. Откройте задачу в панели.")
        return True
    task = session.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id)
                          .with_for_update())
    revision_event = current(session, task_id, kind) if task else None
    required = "backlog" if kind == "plan" else "ready"
    if revision_event is None or revision_event.id != revision or task.status != required:
        runtime.feedback.remove(chat, user, prompt)
        session.rollback()
        await runtime.send(chat, "Редакция изменилась. Откройте задачу в панели.")
        return True
    schema = PlanDecisionRequest if kind == "plan" else ResultDecisionRequest
    try:
        clean = redact_feedback(message.text, runtime.settings)
        decisions.decide(session, task_id, kind, schema(decision=decision, feedback=clean))
        outcome.commit()
        runtime.feedback.remove(chat, user, prompt)
        text = "Замечание сохранено"
    except HTTPException:
        session.rollback()
        runtime.feedback.remove(chat, user, prompt)
        text = "Решение уже изменилось. Откройте задачу в панели."
    await runtime.send(chat, text)
    return True


def redact_feedback(text, settings):
    values = [value.get_secret_value() for value in vars(settings).values()
              if isinstance(value, SecretStr) and value.get_secret_value()]
    for value in sorted(set(values), key=len, reverse=True):
        text = text.replace(value, "[Секрет скрыт]")
    text = re.sub(r"\d{6,12}:[A-Za-z0-9_-]{30,}", "[Секрет скрыт]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[Секрет скрыт]", text)
