"""Ответ на запрос состояния: открытые задачи по проектам, шаблон из БД без LLM и песочниц (D-34).

Песочницы и внешние адаптеры здесь не вызываются: ответ строится только из таблицы tasks.
"""

from typing import Final

from harness_shared.tasks import TaskStatus

from harness_server.security.redaction import redact
from harness_server.services.context import BotContext
from harness_server.services.tasks import list_tasks
from harness_server.telegram.render import NO_WORKSPACE_LABEL, render_status_report, short_title

# Открытые задачи — всё, кроме завершённых и выброшенных в корзину (ТЗ §5, D-34).
OPEN_STATUSES: Final = tuple(
    status for status in TaskStatus if status not in (TaskStatus.MERGED, TaskStatus.TRASH)
)
# Верхняя граница выборки: в MVP один владелец, пагинация не нужна. Неточность счёта — в risks.
STATUS_FETCH_LIMIT: Final = 500


async def build_status_report(ctx: BotContext) -> str:
    """Отчёт об открытых задачах для Telegram: шаблон из БД, без LLM и без песочниц (D-34).

    Группы идут в порядке id проектов, затем задачи проектов вне списка активных (по алфавиту, с
    id вместо названия: отключённый проект), затем задачи без проекта. Весь текст проходит redact:
    в названии задачи может оказаться секрет.
    """
    async with ctx.session_factory() as session:
        tasks = await list_tasks(session, statuses=OPEN_STATUSES, limit=STATUS_FETCH_LIMIT)

    grouped: dict[str | None, list[tuple[str, str]]] = {}
    for task in tasks:
        title = short_title(redact(task.text, ctx.secret_values))
        grouped.setdefault(task.workspace_id, []).append((title, task.status.value))

    workspaces = await ctx.workspaces()
    known_ids = {workspace.id for workspace in workspaces}
    labeled: list[tuple[str, list[tuple[str, str]]]] = []
    for workspace in workspaces:
        if workspace.id in grouped:
            labeled.append((workspace.name, grouped[workspace.id]))
    for workspace_id in sorted(k for k in grouped if k is not None and k not in known_ids):
        labeled.append((workspace_id, grouped[workspace_id]))
    if None in grouped:
        labeled.append((NO_WORKSPACE_LABEL, grouped[None]))

    return redact(render_status_report(labeled, total=len(tasks)), ctx.secret_values)
