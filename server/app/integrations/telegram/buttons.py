from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.models import Task, TaskEvent
from app.schemas.reports import PlanDecisionRequest, ResultDecisionRequest
from app.services import decisions
from app.integrations.telegram.feedback import FEEDBACK_PROMPT, feedback  # noqa: F401
from app.integrations.telegram.revisions import current
from app.integrations.telegram.client import TelegramError

KINDS = {"p": ("plan", PlanDecisionRequest), "r": ("result", ResultDecisionRequest)}
ACTION_CODES = {"a": "approved", "n": "rejected", "t": "trash", "p": "publish",
                "r": "rework", "k": "keep_ready"}


async def _answer(session, runtime, query, text):
    session.rollback()
    await runtime.answer(query.id, text)


async def callback(session, runtime, project, query, outcome):
    try:
        kind, code, raw_revision = query.data[0], query.data[1], query.data[2:]
        kind, schema = KINDS[kind]
        decision = ACTION_CODES[code]
        if len(raw_revision) != 32:
            raise ValueError()
        revision = UUID(hex=raw_revision)
        body = schema(decision=decision, feedback="Проверка" if decision in {"rejected", "rework"} else None)
    except (ValueError, KeyError, IndexError, ValidationError):
        await _answer(session, runtime, query, "Неизвестное действие")
        return
    revision_event = session.get(TaskEvent, revision)
    task = session.scalar(select(Task).where(Task.id == revision_event.task_id,
        Task.project_id == project.id).with_for_update()) if revision_event else None
    if task is None:
        await _answer(session, runtime, query, "Задача недоступна в этом чате")
        return
    latest = current(session, task.id, kind)
    required = "backlog" if kind == "plan" else "ready"
    if latest is None or latest.id != revision or task.status != required:
        await _answer(session, runtime, query, "Редакция изменилась. Откройте задачу в панели.")
        return
    action = revision.hex
    ttl = 900 if decision in {"rejected", "rework"} else None
    if not runtime.actions.claim(action, ttl):
        await _answer(session, runtime, query, "Кнопка уже использована")
        return
    if decision in {"rejected", "rework"}:
        task_id, chat = task.id, str(query.message.chat.id)
        session.rollback()
        prompt_id = None
        try:
            prompt = await runtime.send(chat, FEEDBACK_PROMPT, {"force_reply": True})
            if not isinstance(prompt, dict) or "message_id" not in prompt:
                raise TelegramError("Не удалось запросить замечание")
            prompt_id = prompt["message_id"]
            runtime.feedback.put(chat, query.sender.id, prompt_id,
                                 task_id, kind, decision, revision, action)
            outcome.commit()
        except BaseException:
            session.rollback()
            if prompt_id is not None:
                runtime.feedback.remove(chat, query.sender.id, prompt_id)
            runtime.actions.release(action)
            raise
        await runtime.answer(query.id, "Напишите замечание ответом на сообщение бота")
        return
    try:
        decisions.decide(session, task.id, kind, body)
        outcome.commit()
        answer = "Решение сохранено"
    except HTTPException:
        session.rollback()
        answer = "Решение уже изменилось. Откройте задачу в панели."
    except Exception:
        session.rollback()
        runtime.actions.release(action)
        raise
    await runtime.answer(query.id, answer)


