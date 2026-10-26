"""Диспетчер HTTP-очереди: восстановление, иначе атомарный захват с песочницей."""

import logging
from collections.abc import Mapping

from harness_shared.tasks import TaskKind

from harness_server.worker.context import DispatchContext as DispatchContext
from harness_server.worker.context import build_dispatch_context as build_dispatch_context
from harness_server.worker.execution import run_reserved
from harness_server.worker.pipeline import PIPELINES, Pipeline

logger = logging.getLogger(__name__)


async def dispatch_once(
    ctx: DispatchContext, pipelines: Mapping[TaskKind, Pipeline] = PIPELINES
) -> bool:
    """Пустой реестр не обращается к серверу. Закрепление и токен выдаёт только сервер."""
    if not pipelines:
        return False
    provider_id = ctx.config.sandbox.provider_id
    recovered = await ctx.client.recover(provider_id)
    if recovered is not None:
        pipeline = pipelines.get(recovered.claim.task.kind)
        if pipeline is None:
            logger.info("recovery skipped: no pipeline for kind=%s", recovered.claim.task.kind)
            return False
        await run_reserved(
            ctx, pipeline, recovered.claim, provider_id, cleanup=recovered.sandbox.cleanup_started
        )
        return True
    for pipeline in pipelines.values():
        claim = await ctx.client.claim(pipeline.kind, provider_id)
        if claim is not None:
            await run_reserved(ctx, pipeline, claim, provider_id)
            return True
    return False
