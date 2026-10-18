"""Приём сообщений владельца: запись апдейта, распознавание голоса, задача в choosing и выбор
проекта.

Поток (design.md, решения 1–5): webhook вызывает `record_incoming` и ставит `process_recorded`
в фон. `process_recorded` берёт строку `telegram_updates` под блокировкой `FOR UPDATE SKIP
LOCKED`, создаёт задачу, отмечает апдейт обработанным и очищает payload, и только потом
отправляет карточку. Ошибка Telegram при карточке не создаёт дубль задачи: карточку досылает
`recover_pending` (D-27).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Final

from harness_shared.tasks import TaskEventSource, TaskKind, TaskSource, TaskStatus
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.adapters.stt.protocol import SttError
from harness_server.adapters.telegram.types import TelegramError
from harness_server.db.models import Task, TelegramMessage, TelegramUpdate
from harness_server.domain.errors import DomainError, InvalidTransition, NotFound
from harness_server.security.redaction import redact
from harness_server.services.context import BotContext
from harness_server.services.notify import append_stage, reply, send_task_card
from harness_server.services.tasks import change_status, create_task, select_workspace
from harness_server.telegram.parse import (
    ButtonPress,
    Incoming,
    IncomingText,
    IncomingVoice,
    dedup_key,
    dump_incoming,
    load_incoming,
)
from harness_server.telegram.render import (
    TEXT_ALREADY_CHOSEN,
    TEXT_BAD_BUTTON,
    TEXT_STT_FAILED,
    TEXT_TASK_NOT_FOUND,
    TEXT_UNKNOWN_PROJECT,
    parse_callback_data,
    planning_stage,
)

logger = logging.getLogger(__name__)

MAX_TASK_TEXT: Final = 20_000
# Апдейт и задача старше этого срока считаются брошенными (процесс упал до обработки или отправки).
STALE_AFTER: Final = timedelta(minutes=1)
# Необработанный апдейт старше этого срока не повторяется: его payload (текст и голос владельца)
# очищается без обработки, чтобы ядовитый апдейт не висел в БД и не падал при каждом старте (S2a).
PAYLOAD_TTL: Final = timedelta(hours=24)
_VOICE_FILENAME: Final = "voice.ogg"
_VOICE_DEFAULT_MIME: Final = "audio/ogg"


async def record_incoming(session: AsyncSession, incoming: Incoming) -> bool:
    """Сохраняет нормализованный апдейт. True — строка новая; False — повторная доставка.

    ON CONFLICT DO NOTHING делает вставку атомарной: два одинаковых апдейта не создадут
    две строки.
    """
    kind, external_id = dedup_key(incoming)
    stmt = (
        postgresql.insert(TelegramUpdate)
        .values(kind=kind, external_id=external_id, payload=dump_incoming(incoming))
        .on_conflict_do_nothing(index_elements=["kind", "external_id"])
        .returning(TelegramUpdate.external_id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    return inserted is not None


async def process_recorded(ctx: BotContext, kind: str, external_id: str) -> None:
    """Фоновая обработка одного апдейта. Никогда не бросает: это задача BackgroundTasks webhook.

    В лог попадают только ключ апдейта и имя класса ошибки: без текста и без трассировки.
    Трассировка SQLAlchemy содержит параметры запроса, а в них текст владельца.
    """
    try:
        await _process_locked(ctx, kind, external_id)
    except Exception as exc:
        logger.error(
            "telegram update failed kind=%s id=%s: %s", kind, external_id, type(exc).__name__
        )


async def _process_locked(ctx: BotContext, kind: str, external_id: str) -> None:
    """Обрабатывает апдейт под блокировкой строки. Порядок шагов — design.md, решение 4."""
    async with ctx.session_factory() as lock_session:
        row = (
            await lock_session.execute(
                select(TelegramUpdate)
                .where(
                    TelegramUpdate.kind == kind,
                    TelegramUpdate.external_id == external_id,
                    TelegramUpdate.processed_at.is_(None),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            # Уже обработан или обрабатывается другим процессом.
            return

        incoming = load_incoming(row.payload)
        created: Task | None = None
        stt_failed = False
        if incoming is None:
            logger.warning("telegram update without payload kind=%s id=%s", kind, external_id)
        elif isinstance(incoming, ButtonPress):
            await choose_workspace(ctx, incoming)
        elif isinstance(incoming, IncomingText):
            created = await _create_choosing_task(ctx, incoming.text)
        elif isinstance(incoming, IncomingVoice):
            text = await _transcribe(ctx, incoming)
            if text is None:
                stt_failed = True
            else:
                created = await _create_choosing_task(ctx, text)

        # Апдейт помечается обработанным до отправки карточки: сбой Telegram не создаст дубль
        # задачи.
        row.processed_at = datetime.now(UTC)
        row.payload = None
        await lock_session.commit()

    if stt_failed:
        await reply(ctx, TEXT_STT_FAILED)
    if created is not None:
        try:
            await send_task_card(ctx, created)
        except TelegramError as exc:
            # Карточку досылает recover_pending при старте worker.
            logger.warning(
                "telegram %s failed task=%s: %s", exc.method, created.id, type(exc).__name__
            )


async def _create_choosing_task(ctx: BotContext, text: str) -> Task:
    """Создаёт задачу plan и переводит её в choosing: две короткие транзакции, без сети между ними.

    Секреты удаляются до создания задачи, а не при отправке: так токен не попадает в
    `tasks.text` и не остаётся в БД (S4). Текст обрезается после замены, чтобы не оставить
    от токена фрагмент.
    """
    safe_text = redact(text, ctx.secret_values)[:MAX_TASK_TEXT]
    async with ctx.session_factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.PLAN,
            text=safe_text,
            source=TaskSource.TELEGRAM,
            known_workspace_ids=ctx.known_workspace_ids,
        )
        return await change_status(
            session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.TELEGRAM
        )


async def _transcribe(ctx: BotContext, voice: IncomingVoice) -> str | None:
    """Распознаёт голосовое. None при любой неудаче; причина — в логе без текста аудио.

    Файл скачивается в память только до лимита `voice_max_bytes`, без конвертации (D-29,
    voice-robustness).
    """
    if ctx.stt is None:
        logger.warning("stt not configured")
        return None
    if voice.file_size is not None and voice.file_size > ctx.voice_max_bytes:
        logger.warning("voice file over limit size=%s", voice.file_size)
        return None
    try:
        file = await ctx.telegram.get_file(voice.file_id)
        if file.file_path is None:
            logger.warning("telegram getFile returned no file_path")
            return None
        if file.file_size is not None and file.file_size > ctx.voice_max_bytes:
            logger.warning("voice file over limit size=%s", file.file_size)
            return None
        audio = await ctx.telegram.download_file(file.file_path, max_bytes=ctx.voice_max_bytes)
        text = await ctx.stt.transcribe(
            audio, filename=_VOICE_FILENAME, mime_type=voice.mime_type or _VOICE_DEFAULT_MIME
        )
    except (TelegramError, SttError) as exc:
        logger.warning("voice transcription failed: %s", type(exc).__name__)
        return None
    stripped = text.strip()[:MAX_TASK_TEXT]
    return stripped if stripped else None


async def choose_workspace(ctx: BotContext, press: ButtonPress) -> None:
    """Нажатие кнопки проекта: choosing → planning с workspace, затем этап в карточке.

    Данные кнопки приходят от клиента, поэтому формат, наличие workspace в конфиге и задача
    в БД проверяются до перехода. Ответы на нажатие уходят при любом исходе, чтобы у кнопки
    не висели «часики».
    """
    parsed = parse_callback_data(press.data)
    if parsed is None:
        await _answer(ctx, press.callback_query_id, TEXT_BAD_BUTTON)
        return
    task_id, workspace_id = parsed
    workspace = next((w for w in ctx.workspaces if w.id == workspace_id), None)
    if workspace is None:
        await _answer(ctx, press.callback_query_id, TEXT_UNKNOWN_PROJECT)
        return

    try:
        async with ctx.session_factory() as session:
            task = await select_workspace(
                session,
                task_id,
                workspace_id,
                known_workspace_ids=ctx.known_workspace_ids,
                source=TaskEventSource.TELEGRAM,
            )
    except NotFound:
        await _answer(ctx, press.callback_query_id, TEXT_TASK_NOT_FOUND)
        return
    except InvalidTransition:
        await _answer(ctx, press.callback_query_id, TEXT_ALREADY_CHOSEN)
        return

    await _answer(ctx, press.callback_query_id, None)
    await append_stage(ctx, task.id, planning_stage(workspace.name))


async def _answer(ctx: BotContext, callback_query_id: str, text: str | None) -> None:
    """Ответ на нажатие кнопки.

    Telegram отвергает ответ на старый callback. Это не ошибка обработки, поэтому ошибка
    логируется и не пробрасывается. Текст проходит redact как любой исходящий текст.
    """
    safe_text = None if text is None else redact(text, ctx.secret_values)
    try:
        await ctx.telegram.answer_callback_query(callback_query_id, text=safe_text)
    except TelegramError as exc:
        logger.warning("telegram %s failed: %s", exc.method, type(exc).__name__)


async def recover_pending(ctx: BotContext, *, stale_after: timedelta = STALE_AFTER) -> int:
    """Дообрабатывает апдейты, принятые до рестарта, и досылает карточки задачам без сообщения.

    Вызывается при старте worker. Апдейт берётся, если он не обработан и получен раньше порога
    `stale_after`. Если он старше `PAYLOAD_TTL`, payload очищается без обработки (S2a).
    Задача `telegram` в new или choosing без карточки получает карточку; new сначала переводится
    в choosing. Возвращает число апдейтов, которые обработаны или списаны. Ошибки отдельных
    задач логируются и не останавливают восстановление.
    """
    now = datetime.now(UTC)
    threshold = now - stale_after
    expired_before = now - PAYLOAD_TTL
    async with ctx.session_factory() as session:
        rows = (
            await session.execute(
                select(TelegramUpdate.kind, TelegramUpdate.external_id, TelegramUpdate.received_at)
                .where(
                    TelegramUpdate.processed_at.is_(None),
                    TelegramUpdate.received_at < threshold,
                )
                .order_by(TelegramUpdate.received_at)
            )
        ).all()
    expired = [
        (kind, external_id) for kind, external_id, received in rows if received < expired_before
    ]
    retry = [
        (kind, external_id) for kind, external_id, received in rows if received >= expired_before
    ]

    if expired:
        await _drop_expired_payloads(ctx, expired)
    for kind, external_id in retry:
        await process_recorded(ctx, kind, external_id)

    async with ctx.session_factory() as session:
        orphans = list(
            (
                await session.execute(
                    select(Task)
                    .outerjoin(TelegramMessage, TelegramMessage.task_id == Task.id)
                    .where(
                        Task.source == TaskSource.TELEGRAM,
                        Task.status.in_([TaskStatus.NEW, TaskStatus.CHOOSING]),
                        Task.created_at < threshold,
                        TelegramMessage.task_id.is_(None),
                    )
                    .order_by(Task.created_at)
                )
            )
            .scalars()
            .all()
        )

    cards = 0
    for task in orphans:
        try:
            current = task
            if task.status == TaskStatus.NEW:
                async with ctx.session_factory() as session:
                    current = await change_status(
                        session, task.id, TaskStatus.CHOOSING, source=TaskEventSource.TELEGRAM
                    )
            await send_task_card(ctx, current)
            cards += 1
        except (TelegramError, DomainError) as exc:
            logger.warning("telegram recovery failed task=%s: %s", task.id, type(exc).__name__)

    logger.info(
        "telegram recovery updates=%d expired=%d cards=%d",
        len(rows),
        len(expired),
        cards,
    )
    return len(rows)


async def _drop_expired_payloads(ctx: BotContext, expired: list[tuple[str, str]]) -> None:
    """Помечает просроченные апдейты обработанными и очищает payload, не выполняя их.

    Условие `processed_at IS NULL` в UPDATE защищает от гонки: апдейт, который успела обработать
    другая часть процесса, не трогается. В лог — только ключ апдейта и причина, без текста.
    """
    now = datetime.now(UTC)
    async with ctx.session_factory() as session:
        for kind, external_id in expired:
            await session.execute(
                update(TelegramUpdate)
                .where(
                    TelegramUpdate.kind == kind,
                    TelegramUpdate.external_id == external_id,
                    TelegramUpdate.processed_at.is_(None),
                )
                .values(processed_at=now, payload=None)
            )
        await session.commit()
    for kind, external_id in expired:
        logger.warning(
            "telegram update expired kind=%s id=%s: payload dropped unprocessed",
            kind,
            external_id,
        )
