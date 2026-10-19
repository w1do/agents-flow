"""Сообщения владельцу: карточка задачи, дописывание этапов и короткие ответы.

Одна задача — одно сообщение (D-28, решение 9): этапы дописываются строками и редактируются.
Сеть вызывается вне транзакций, где это возможно; сессии короткие (контекст BotContext).
Весь текст проходит redact: текст задачи очищается до краткого названия и усечения, а готовое
сообщение очищается ещё раз. Ошибки Telegram при отправке не пробрасываются наружу, кроме
send_task_card (её досылает recover_pending).
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from harness_server.adapters.telegram.types import MessageNotEditable, TelegramError
from harness_server.config import WorkspaceConfig
from harness_server.db.models import Task, TelegramMessage
from harness_server.security.redaction import redact
from harness_server.services.context import BotContext
from harness_server.services.tasks import get_task
from harness_server.telegram.render import (
    STAGE_CHOOSING,
    clarify_keyboard,
    clarify_text,
    render_card,
    short_title,
    stage_line,
    workspace_keyboard,
)

logger = logging.getLogger(__name__)


async def send_task_card(
    ctx: BotContext, task: Task, *, workspaces: Sequence[WorkspaceConfig] | None = None
) -> None:
    """Отправляет карточку задачи с кнопками выбора проекта. Идемпотентна: вторая карточка не
    уходит.

    workspaces — кнопки маршрутизатора (не больше трёх); None — все workspace из конфига (D-13).
    TelegramError пробрасывается: вызывающий решает, что делать (процесс досылает карточку позже).
    """
    async with ctx.session_factory() as session:
        if await session.get(TelegramMessage, task.id) is not None:
            return
    source = _clean_text(ctx, task.text)
    line = stage_line(short_title(source), STAGE_CHOOSING)
    text = redact(render_card(source, [line]), ctx.secret_values)
    message_id = await ctx.telegram.send_message(
        ctx.owner_chat_id,
        text,
        reply_markup=workspace_keyboard(
            task.id, ctx.workspaces if workspaces is None else workspaces
        ),
    )
    async with ctx.session_factory() as session:
        session.add(
            TelegramMessage(
                task_id=task.id,
                chat_id=ctx.owner_chat_id,
                message_id=message_id,
                lines=[line],
            )
        )
        await session.commit()


async def append_stage(ctx: BotContext, task_id: UUID, stage: str) -> None:
    """Дописывает строку этапа в сообщение задачи и перерисовывает его.

    Строка карточки блокируется FOR UPDATE, поэтому два этапа одной задачи не потеряют
    строки друг друга. Ошибки Telegram логируются без текста. Строки этапов сохраняются,
    и следующая правка покажет их все.
    """
    async with ctx.session_factory() as session:
        task = await get_task(session, task_id)
        source = _clean_text(ctx, task.text)
        line = stage_line(short_title(source), stage)
        card = (
            await session.execute(
                select(TelegramMessage).where(TelegramMessage.task_id == task_id).with_for_update()
            )
        ).scalar_one_or_none()

        if card is None:
            text = redact(render_card(source, [line]), ctx.secret_values)
            try:
                message_id = await ctx.telegram.send_message(ctx.owner_chat_id, text)
            except TelegramError as exc:
                _log_failure(exc, task_id)
                await session.rollback()
                return
            session.add(
                TelegramMessage(
                    task_id=task_id,
                    chat_id=ctx.owner_chat_id,
                    message_id=message_id,
                    lines=[line],
                )
            )
            await session.commit()
            return

        # Новый список, а не append: JSONB без MutableList не видит изменения на месте.
        lines = [*card.lines, line]
        text = redact(render_card(source, lines), ctx.secret_values)
        try:
            # Без reply_markup: Bot API убирает инлайн-клавиатуру при редактировании.
            await ctx.telegram.edit_message_text(card.chat_id, card.message_id, text)
        except MessageNotEditable as exc:
            _log_failure(exc, task_id)
            try:
                card.message_id = await ctx.telegram.send_message(card.chat_id, text)
            except TelegramError as send_exc:
                _log_failure(send_exc, task_id)
        except TelegramError as exc:
            _log_failure(exc, task_id)
        card.lines = lines
        await session.commit()


async def reply(ctx: BotContext, text: str) -> None:
    """Короткий ответ владельцу без привязки к задаче. Ошибка Telegram логируется, не
    пробрасывается."""
    try:
        await ctx.telegram.send_message(ctx.owner_chat_id, redact(text, ctx.secret_values))
    except TelegramError as exc:
        logger.warning("telegram %s failed: %s", exc.method, type(exc).__name__)


async def send_clarify(ctx: BotContext, routing_id: UUID, title: str) -> None:
    """Вопрос «Сделать задачу / Показать статус» при низкой уверенности (D-33).

    Ошибка Telegram логируется: владелец повторит команду, задача до нажатия не создана.
    """
    text = redact(clarify_text(title), ctx.secret_values)
    try:
        await ctx.telegram.send_message(
            ctx.owner_chat_id, text, reply_markup=clarify_keyboard(routing_id)
        )
    except TelegramError as exc:
        logger.warning(
            "telegram %s failed routing=%s: %s", exc.method, routing_id, type(exc).__name__
        )


async def close_prompt(ctx: BotContext, chat_id: int, message_id: int, text: str) -> None:
    """Заменяет текст сообщения с кнопками и убирает клавиатуру. Ошибки Telegram логируются.

    Без reply_markup Bot API убирает инлайн-клавиатуру: повторно нажать уже нельзя.
    """
    try:
        await ctx.telegram.edit_message_text(chat_id, message_id, redact(text, ctx.secret_values))
    except TelegramError as exc:
        logger.warning("telegram %s failed: %s", exc.method, type(exc).__name__)


def _clean_text(ctx: BotContext, text: str) -> str:
    """Текст задачи без секретов до любой обрезки. Иначе усечение оставило бы от токена фрагмент,
    который шаблоны redact уже не узнают."""
    return redact(text, ctx.secret_values)


def _log_failure(exc: TelegramError, task_id: UUID) -> None:
    """Предупреждение без текста задачи и без текста ошибки: только метод и класс исключения."""
    logger.warning("telegram %s failed task=%s: %s", exc.method, task_id, type(exc).__name__)
