"""Зеркало пунктов OpenSpec; операции сериализуются блокировкой плана."""

from collections.abc import Sequence

from harness_shared.planning import SpecItemOut, SpecSyncIn
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.db.models import Project, SpecItem, Task
from harness_server.domain.errors import Forbidden
from harness_server.security.redaction import redact


async def sync_items(
    session: AsyncSession, plan: Task, body: SpecSyncIn, secrets: Sequence[str]
) -> list[SpecItemOut]:
    """Upsert своих пунктов, без перехвата ключей другого плана."""
    # Уникальность ключа общая для workspace, поэтому разные планы также сериализуются.
    await session.scalar(
        select(Project.id).where(Project.id == plan.workspace_id).with_for_update()
    )
    rows: list[SpecItem] = []
    for item in body.items:
        row = await session.scalar(
            select(SpecItem).where(
                SpecItem.workspace_id == plan.workspace_id,
                SpecItem.change_id == body.change_id,
                SpecItem.key == item.key,
            )
        )
        if row is not None and row.plan_task_id != plan.id:
            raise Forbidden("foreign_spec_item")
        if row is None:
            row = SpecItem(
                workspace_id=plan.workspace_id,
                plan_task_id=plan.id,
                change_id=body.change_id,
                key=item.key,
            )
            session.add(row)
        row.text = redact(item.text, secrets)
        row.status = redact(item.status, secrets)
        rows.append(row)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return [SpecItemOut.model_validate(row) for row in rows]
