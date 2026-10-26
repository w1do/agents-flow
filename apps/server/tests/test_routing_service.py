"""Сервис маршрутизации: промпт, разбор ответа, классификация с фейком, запись в routings."""

from collections.abc import Callable

import pytest
from harness_server.adapters.polza import FakeRouter, RouterError
from harness_server.adapters.telegram import FakeTelegramClient
from harness_server.db.ids import uuid7
from harness_server.db.models import Routing
from harness_server.domain.errors import AlreadyResolved, NotFound
from harness_server.services.context import BotContext
from harness_server.services.routing import (
    PROMPT_MARKER,
    RouteResult,
    build_system_prompt,
    claim_clarification,
    classify,
    extract_json_object,
    load_prompt_template,
    parse_decision,
    rank_candidates,
    record_choice,
    record_routing,
)
from harness_server.services.tasks import create_task
from harness_shared.projects import ProjectRepo, Workspace
from harness_shared.routing import (
    CommandClass,
    RoutingDecision,
    RoutingDecisionKind,
    WorkspaceCandidate,
)
from harness_shared.tasks import TaskKind, TaskSource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Значение из conftest.make_bot_context: секрет, который не должен уйти наружу.
SECRET = "test-webhook-secret-0123456789abcdef"
DEMO = Workspace(
    id="demo",
    name="Демо-проект",
    voice_aliases=["демо", "демка"],
    repo=ProjectRepo(provider="gitlab", project="group/demo"),
)
SHOP = Workspace(
    id="shop",
    name="Магазин",
    voice_aliases=[],
    repo=ProjectRepo(provider="gitlab", project="group/shop"),
)


def _decision(workspaces: list[tuple[str, float]]) -> RoutingDecision:
    return RoutingDecision.model_validate(
        {
            "class": "work",
            "confidence": 0.9,
            "workspaces": [{"id": i, "score": s} for i, s in workspaces],
            "title": "",
        }
    )


def _route(
    decision: RoutingDecisionKind = RoutingDecisionKind.AUTO,
    command_class: CommandClass = CommandClass.WORK,
) -> RouteResult:
    return RouteResult(
        decision=decision,
        command_class=command_class,
        confidence=0.9,
        candidates=(WorkspaceCandidate(id="demo", score=0.8),),
        raw_response=None,
        error=None,
    )


# --- промпт и разбор ответа (без БД) ---


def test_prompt_template_has_marker() -> None:
    assert PROMPT_MARKER in load_prompt_template()


def test_build_system_prompt_lists_workspaces() -> None:
    prompt = build_system_prompt((DEMO, SHOP))

    assert PROMPT_MARKER not in prompt
    assert "- id: demo; название: Демо-проект; другие названия: демо, демка" in prompt
    assert "- id: shop; название: Магазин; другие названия: —" in prompt
    assert prompt.splitlines()[0] == load_prompt_template().splitlines()[0]


def test_extract_json_plain() -> None:
    assert extract_json_object('{"class": "work"}') == {"class": "work"}


def test_extract_json_code_fence() -> None:
    content = '```json\n{"class": "status", "confidence": 0.9}\n```'

    assert extract_json_object(content) == {"class": "status", "confidence": 0.9}


def test_extract_json_with_prefix_text() -> None:
    assert extract_json_object('Вот ответ: {"class": "unknown"}') == {"class": "unknown"}


@pytest.mark.parametrize("content", ["[1]", "текст", "", "{не json"])
def test_extract_json_non_object_returns_none(content: str) -> None:
    assert extract_json_object(content) is None


def test_parse_decision_invalid_returns_none() -> None:
    assert parse_decision('{"class": "check", "confidence": 0.9}') is None


def test_rank_drops_unknown_workspace() -> None:
    # Модель вернула несуществующий проект: кнопки для него не будет.
    decision = _decision([("ghost", 0.9), ("demo", 0.5)])

    ranked = rank_candidates(decision, ("demo", "shop"))

    assert tuple(c.id for c in ranked) == ("demo",)


def test_rank_dedups_sorts_and_limits() -> None:
    decision = _decision([("a", 0.2), ("b", 0.9), ("a", 0.99), ("c", 0.5), ("d", 0.4), ("e", 0.1)])

    ranked = rank_candidates(decision, ("a", "b", "c", "d", "e"))

    assert tuple(c.id for c in ranked) == ("b", "c", "d")
    assert ranked[0].score == 0.9


# --- классификация с фейком маршрутизатора ---


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_without_router_is_fallback(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    ctx = make_bot_context(committed_session_factory, telegram=FakeTelegramClient())

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.FALLBACK
    assert result.error == "not_configured"
    assert result.candidates == ()


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_router_error_is_fallback(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    router = FakeRouter(error=RouterError("timeout"))
    ctx = make_bot_context(committed_session_factory, telegram=FakeTelegramClient(), router=router)

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.FALLBACK
    assert result.error == "timeout"
    assert result.raw_response is None


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_invalid_content_is_fallback(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
) -> None:
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=FakeRouter("не json"),
    )

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.FALLBACK
    assert result.error == "invalid_decision"
    assert result.raw_response == "не json"


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_low_confidence_is_clarify(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    routing_content: Callable[..., str],
) -> None:
    content = routing_content("work", 0.4, [("demo", 0.8)])
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=FakeRouter(content),
        routing_min_confidence=0.6,
    )

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.CLARIFY


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_threshold_is_inclusive(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    routing_content: Callable[..., str],
) -> None:
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=FakeRouter(routing_content("work", 0.6, [("demo", 0.8)])),
        routing_min_confidence=0.6,
    )

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.AUTO


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_confident_work_is_auto(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    routing_content: Callable[..., str],
) -> None:
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=FakeRouter(routing_content("work", 0.9, [("demo", 0.8), ("shop", 0.3)])),
    )

    result = await classify(ctx, "сделай")

    assert result.decision is RoutingDecisionKind.AUTO
    assert result.command_class is CommandClass.WORK
    assert [c.id for c in result.candidates] == ["demo", "shop"]
    assert result.error is None


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_limits_user_text(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    routing_content: Callable[..., str],
) -> None:
    router = FakeRouter(routing_content("unknown", 0.9))
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=router,
    )

    await classify(ctx, "а" * 5000)

    assert len(router.calls[0][1]) == 2000


@pytest.mark.asyncio(loop_scope="session")
async def test_classify_redacts_raw_response(
    committed_session_factory: async_sessionmaker[AsyncSession],
    make_bot_context: Callable[..., BotContext],
    routing_content: Callable[..., str],
) -> None:
    content = routing_content("unknown", 0.9, title=f"секрет {SECRET}")
    ctx = make_bot_context(
        committed_session_factory,
        telegram=FakeTelegramClient(),
        router=FakeRouter(content),
    )

    result = await classify(ctx, "какая погода")

    assert result.raw_response is not None
    assert "[REDACTED]" in result.raw_response
    assert SECRET not in result.raw_response


# --- запись в routings и уточнение (БД) ---


@pytest.mark.asyncio(loop_scope="session")
async def test_record_routing_persists_fields(
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = _route()

    async with committed_session_factory() as session:
        routing = await record_routing(session, result, task_id=None)

    async with committed_session_factory() as session:
        row = await session.get(Routing, routing.id)
    assert row is not None
    assert row.task_id is None
    assert row.decision is RoutingDecisionKind.AUTO
    assert row.command_class is CommandClass.WORK
    assert row.options == [{"id": "demo", "score": 0.8}]
    assert row.confidence == 0.9


@pytest.mark.asyncio(loop_scope="session")
async def test_claim_clarification_marks_resolved(
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = RouteResult(
        decision=RoutingDecisionKind.CLARIFY,
        command_class=CommandClass.WORK,
        confidence=0.4,
        candidates=(WorkspaceCandidate(id="demo", score=0.8),),
        raw_response=None,
        error=None,
    )
    async with committed_session_factory() as session:
        routing = await record_routing(session, result, task_id=None, source_text="сделай")

    async with committed_session_factory() as session:
        claimed = await claim_clarification(session, routing.id)

    assert claimed.source_text == "сделай"
    assert [c.id for c in claimed.candidates] == ["demo"]
    async with committed_session_factory() as session:
        row = await session.get(Routing, routing.id)
    assert row is not None
    assert row.resolved_at is not None
    assert row.source_text is None


@pytest.mark.asyncio(loop_scope="session")
async def test_claim_twice_raises_already_resolved(
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = RouteResult(
        decision=RoutingDecisionKind.CLARIFY,
        command_class=CommandClass.WORK,
        confidence=0.4,
        candidates=(),
        raw_response=None,
        error=None,
    )
    async with committed_session_factory() as session:
        routing = await record_routing(session, result, task_id=None, source_text="сделай")
    async with committed_session_factory() as session:
        await claim_clarification(session, routing.id)

    with pytest.raises(AlreadyResolved):
        async with committed_session_factory() as session:
            await claim_clarification(session, routing.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_claim_missing_or_not_clarify_raises_not_found(
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with committed_session_factory() as session:
        auto = await record_routing(session, _route(), task_id=None)

    with pytest.raises(NotFound):
        async with committed_session_factory() as session:
            await claim_clarification(session, uuid7())
    with pytest.raises(NotFound):
        async with committed_session_factory() as session:
            await claim_clarification(session, auto.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_record_choice_sets_chosen_workspace(
    committed_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Выбор кнопкой пишется в routings по task_id; здесь достаточно строки с задачей.
    async with committed_session_factory() as session:
        task = await create_task(
            session,
            kind=TaskKind.PLAN,
            text="сделай",
            source=TaskSource.TELEGRAM,
            known_workspace_ids=("demo", "shop"),
        )
    async with committed_session_factory() as session:
        await record_routing(session, _route(), task_id=task.id)

    async with committed_session_factory() as session:
        await record_choice(session, task.id, "demo")

    async with committed_session_factory() as session:
        chosen = (
            await session.execute(
                select(Routing.chosen_workspace_id).where(Routing.task_id == task.id)
            )
        ).scalar_one()
    assert chosen == "demo"
