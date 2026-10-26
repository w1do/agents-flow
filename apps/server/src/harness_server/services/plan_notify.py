"""Краткий итог планирования в существующей карточке Telegram."""

from collections.abc import Sequence
from uuid import UUID

from harness_shared.tasks import TaskKind, TaskStatus
from sqlalchemy import select

from harness_server.db.models import Task
from harness_server.security.redaction import redact
from harness_server.services.context import BotContext
from harness_server.telegram.render import short_title


def planning_summary(titles: Sequence[str], secrets: Sequence[str] = ()) -> str:
    """Очищает названия до усечения, чтобы не оставить фрагмент токена."""
    names = [short_title(redact(title, secrets)) for title in titles]
    return "\n".join(
        [
            f"спецификация готова, задач: {len(names)}",
            *[f"• {name}" for name in names],
        ]
    )


async def plan_ready(ctx: BotContext, task_id: UUID) -> None:
    """Идемпотентно дописывает итог только готового плана; worker не вызывает Telegram."""
    from harness_server.services.notify import append_stage

    async with ctx.session_factory() as session:
        plan = await session.get(Task, task_id)
        if plan is None or plan.kind != TaskKind.PLAN or plan.status != TaskStatus.READY:
            return
        titles = list(
            await session.scalars(
                select(Task.text)
                .where(
                    Task.parent_id == task_id,
                    Task.kind == TaskKind.IMPLEMENT,
                )
                .order_by(Task.created_at, Task.id)
            )
        )
    await append_stage(
        ctx,
        task_id,
        planning_summary(titles, ctx.secret_values),
        deduplicate=True,
    )
