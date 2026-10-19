"""Разбор итога агента: исчерпанный лимит подписки Claude (mvp-06, D-54). Чистые функции, без БД."""

import json
from typing import Any

import pytest
from harness_server.services.agent_result import (
    LIMIT_TEXT_MAX_LEN,
    AgentRun,
    AgentState,
    parse_result,
)

LIMIT_TEXT = "You've hit your session limit · resets 5:30pm (UTC)"


def _line(**fields: Any) -> str:
    event: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "session_id": "s-1",
    }
    event.update(fields)
    return json.dumps(event)


def _finished(line: str, exit_code: int = 0) -> AgentRun:
    return AgentRun(state=AgentState.FINISHED, exit_code=exit_code, result=parse_result([line]))


def test_limit_message_with_one_turn_is_not_success() -> None:
    run = _finished(_line(result=LIMIT_TEXT))

    assert run.result is not None
    assert run.result.limit_reached is True
    assert run.succeeded is False


def test_limit_error_variant_is_detected() -> None:
    run = _finished(
        _line(is_error=True, num_turns=3, result="Usage limit reached for this plan"), exit_code=1
    )

    assert run.result is not None
    assert run.result.limit_reached is True
    assert run.succeeded is False


@pytest.mark.parametrize(
    "text",
    [
        "You’ve hit your usage limit",
        "  you've HIT your limit  ",
        "Hit your session limit, resets 5pm",
        "Usage limit reached for this plan",
        "Claude usage limit reached|1760000000",
    ],
)
def test_limit_text_variants_are_detected(text: str) -> None:
    result = parse_result([_line(result=text)])

    assert result is not None
    assert result.limit_reached is True


def test_bare_rate_limit_phrase_is_not_limit() -> None:
    """Общая фраза «rate limit» без явного маркера лимита подписки не распознаётся."""
    run = _finished(_line(result="Hit a rate limit once, retried and finished."))

    assert run.result is not None
    assert run.result.limit_reached is False
    assert run.succeeded is True


def test_one_turn_summary_longer_than_limit_bound_is_not_limit() -> None:
    """Итог в один ход длиннее LIMIT_TEXT_MAX_LEN с фразой о лимите — сводка работы, не лимит."""
    summary = "Summary: the usage limit reached threshold was checked. " + "x" * 300
    assert len(summary) > LIMIT_TEXT_MAX_LEN

    run = _finished(_line(num_turns=1, result=summary))

    assert run.result is not None
    assert run.result.limit_reached is False
    assert run.succeeded is True


def test_multi_turn_answer_mentioning_limit_is_not_limit() -> None:
    """Ворота по числу ходов: короткий текст о лимите в диалоге из 5 ходов не распознаётся."""
    run = _finished(
        _line(num_turns=5, result="You've hit your session limit in the docs, see below.")
    )

    assert run.result is not None
    assert run.result.limit_reached is False
    assert run.succeeded is True


def test_error_result_without_limit_text_is_not_limit() -> None:
    run = _finished(_line(is_error=True, result="Compilation failed"), exit_code=1)

    assert run.result is not None
    assert run.result.limit_reached is False
    assert run.succeeded is False
