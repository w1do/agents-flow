"""Маршрутизация текста владельца: один вызов модели, сервер выбирает путь (mvp-05, D-31…D-33).

Модель только предлагает класс и кандидатов. Этот модуль проверяет ответ, отбрасывает неизвестные
id, ограничивает список и пишет каждое решение в `routings` (D-32). Текст команды до вызова
проходит redact (делает вызывающий), ответ модели — redact до записи.
"""

import json
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from importlib import resources
from typing import Any, Final
from uuid import UUID

from harness_shared.routing import (
    CommandClass,
    RoutingDecision,
    RoutingDecisionKind,
    WorkspaceCandidate,
)
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from harness_server.adapters.polza.protocol import RouterError
from harness_server.config import WorkspaceConfig
from harness_server.db.models import Routing
from harness_server.domain.errors import AlreadyResolved, NotFound
from harness_server.security.redaction import redact
from harness_server.services.context import BotContext

logger = logging.getLogger(__name__)

ROUTING_TEXT_LIMIT: Final = 2000  # символов текста владельца в запросе к модели
MAX_CANDIDATES: Final = 3
RAW_RESPONSE_LIMIT: Final = 4000  # символов сырого ответа в routings.raw_response
PROMPT_MARKER: Final = "<<WORKSPACES>>"
ERROR_NOT_CONFIGURED: Final = "not_configured"
ERROR_INVALID_DECISION: Final = "invalid_decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class RouteResult:
    """Итог классификации до записи в БД."""

    decision: RoutingDecisionKind
    command_class: CommandClass
    confidence: float | None
    candidates: tuple[WorkspaceCandidate, ...]  # после фильтра, ≤ 3, по убыванию score
    raw_response: str | None  # после redact, ≤ RAW_RESPONSE_LIMIT
    error: str | None  # причина fallback


@dataclass(frozen=True, slots=True)
class Clarification:
    """Захваченное уточнение: текст команды и сохранённые кандидаты."""

    source_text: str
    candidates: tuple[WorkspaceCandidate, ...]


@cache
def load_prompt_template() -> str:
    """Шаблон системного промпта из пакета services/prompts (routing.md)."""
    return (
        resources.files("harness_server.services.prompts")
        .joinpath("routing.md")
        .read_text(encoding="utf-8")
    )


def build_system_prompt(workspaces: Sequence[WorkspaceConfig]) -> str:
    """Промпт с перечнем проектов из harness.yaml.

    Замена маркера через str.replace: в промпте есть фигурные скобки JSON, str.format их сломает.
    """
    lines = []
    for workspace in workspaces:
        aliases = ", ".join(workspace.voice_aliases) if workspace.voice_aliases else "—"
        lines.append(
            f"- id: {workspace.id}; название: {workspace.name}; другие названия: {aliases}"
        )
    return load_prompt_template().replace(PROMPT_MARKER, "\n".join(lines))


def extract_json_object(content: str) -> dict[str, Any] | None:
    """Первый JSON-объект из ответа модели; None, если объекта нет.

    Покрывает Markdown-ограждение и текст перед объектом: модель не всегда отвечает чистым JSON.
    """
    stripped = content.strip()
    try:
        obj: Any = json.loads(stripped)
    except ValueError:
        start = stripped.find("{")
        if start < 0:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(stripped, start)
        except ValueError:
            return None
    return obj if isinstance(obj, dict) else None


def parse_decision(content: str) -> RoutingDecision | None:
    """Проверяет ответ модели по схеме RoutingDecision. None — ответ невалиден."""
    obj = extract_json_object(content)
    if obj is None:
        return None
    try:
        return RoutingDecision.model_validate(obj)
    except ValidationError:
        return None


def rank_candidates(
    decision: RoutingDecision, known_workspace_ids: Collection[str]
) -> tuple[WorkspaceCandidate, ...]:
    """Кандидаты только из конфига, без повторов, по убыванию score, не больше MAX_CANDIDATES.

    Сортировка стабильная: при равных score порядок ответа модели сохраняется.
    """
    known = set(known_workspace_ids)
    seen: set[str] = set()
    filtered: list[WorkspaceCandidate] = []
    for candidate in decision.workspaces:
        if candidate.id not in known or candidate.id in seen:
            continue
        seen.add(candidate.id)
        filtered.append(candidate)
    ranked = sorted(filtered, key=lambda c: c.score, reverse=True)
    return tuple(ranked[:MAX_CANDIDATES])


def _fallback(error: str, raw: str | None) -> RouteResult:
    """Запасной путь: класс work, без кандидатов. Причина попадает в routings.error."""
    return RouteResult(
        decision=RoutingDecisionKind.FALLBACK,
        command_class=CommandClass.WORK,
        confidence=None,
        candidates=(),
        raw_response=raw,
        error=error,
    )


async def classify(ctx: BotContext, text: str) -> RouteResult:
    """Классифицирует текст одним вызовом маршрутизатора. Не бросает исключений и не пишет в БД.

    Вызывающий передаёт уже очищенный от секретов текст. Ошибки маршрутизатора превращаются в
    запасной путь с причиной; в лог попадают класс, решение и число кандидатов, но не текст.
    """
    if ctx.router is None:
        return _fallback(ERROR_NOT_CONFIGURED, None)
    try:
        reply = await ctx.router.complete(
            system_prompt=build_system_prompt(ctx.workspaces),
            user_text=text[:ROUTING_TEXT_LIMIT],
        )
    except RouterError as exc:
        logger.warning("routing failed: %s", exc.reason)
        return _fallback(exc.reason, None)

    raw = redact(reply.content, ctx.secret_values)[:RAW_RESPONSE_LIMIT]
    decision = parse_decision(reply.content)
    if decision is None:
        logger.warning("routing invalid decision")
        return _fallback(ERROR_INVALID_DECISION, raw)

    candidates = rank_candidates(decision, ctx.known_workspace_ids)
    kind = (
        RoutingDecisionKind.CLARIFY
        if decision.confidence < ctx.routing_min_confidence
        else RoutingDecisionKind.AUTO
    )
    logger.info(
        "routing decision=%s class=%s confidence=%s candidates=%d",
        kind,
        decision.command_class,
        decision.confidence,
        len(candidates),
    )
    return RouteResult(
        decision=kind,
        command_class=decision.command_class,
        confidence=decision.confidence,
        candidates=candidates,
        raw_response=raw,
        error=None,
    )


async def record_routing(
    session: AsyncSession,
    result: RouteResult,
    *,
    task_id: UUID | None,
    source_text: str | None = None,
) -> Routing:
    """Пишет решение маршрутизации. source_text задаётся только для уточнения (D-33)."""
    routing = Routing(
        task_id=task_id,
        command_class=result.command_class,
        decision=result.decision,
        options=[{"id": c.id, "score": c.score} for c in result.candidates],
        raw_response=result.raw_response,
        confidence=result.confidence,
        error=result.error,
        source_text=source_text,
    )
    session.add(routing)
    await session.commit()
    await session.refresh(routing)
    return routing


async def claim_clarification(session: AsyncSession, routing_id: UUID) -> Clarification:
    """Забирает уточнение: помечает resolved_at и обнуляет текст. Повтор — AlreadyResolved.

    FOR UPDATE не даёт двум нажатиям пройти одновременно. Текст команды возвращается до обнуления,
    чтобы вызывающий создал по нему задачу.
    """
    row = (
        await session.execute(
            select(Routing)
            .where(Routing.id == routing_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None or row.decision != RoutingDecisionKind.CLARIFY:
        raise NotFound("routing", routing_id)
    if row.resolved_at is not None:
        raise AlreadyResolved("routing", routing_id)
    if row.source_text is None:
        raise NotFound("routing", routing_id)

    text = row.source_text
    candidates: list[WorkspaceCandidate] = []
    for item in row.options:
        try:
            candidates.append(WorkspaceCandidate.model_validate(item))
        except ValidationError:
            continue
    row.resolved_at = datetime.now(UTC)
    row.source_text = None
    await session.commit()
    return Clarification(source_text=text, candidates=tuple(candidates))


async def attach_task(session: AsyncSession, routing_id: UUID, task_id: UUID) -> None:
    """Связывает решение уточнения с задачей, созданной по нажатию «Сделать задачу»."""
    await session.execute(update(Routing).where(Routing.id == routing_id).values(task_id=task_id))
    await session.commit()


async def record_choice(session: AsyncSession, task_id: UUID, workspace_id: str) -> None:
    """Записывает выбранный кнопкой workspace в решение маршрутизации задачи (ТЗ §5, D-32)."""
    await session.execute(
        update(Routing).where(Routing.task_id == task_id).values(chosen_workspace_id=workspace_id)
    )
    await session.commit()
