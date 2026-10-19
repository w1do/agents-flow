"""Модели ответа маршрутизатора: валидация JSON модели на стороне сервера (D-33)."""

from typing import Any

import pytest
from harness_shared.routing import (
    CommandClass,
    RoutingDecision,
    WorkspaceCandidate,
)
from pydantic import ValidationError


def _decision(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "class": "work",
        "confidence": 0.9,
        "workspaces": [{"id": "demo", "score": 0.8}],
        "title": "добавь экспорт",
    }
    data.update(overrides)
    return data


def test_decision_parses_class_alias() -> None:
    decision = RoutingDecision.model_validate(_decision())

    assert decision.command_class is CommandClass.WORK
    assert decision.confidence == 0.9
    assert decision.workspaces[0].id == "demo"


def test_decision_ignores_extra_fields() -> None:
    decision = RoutingDecision.model_validate(
        _decision(extra="лишнее", workspaces=[{"id": "demo", "score": 0.8, "note": "x"}])
    )

    assert decision.command_class is CommandClass.WORK
    assert len(decision.workspaces) == 1


def test_decision_rejects_unknown_class() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(_decision(**{"class": "check"}))


@pytest.mark.parametrize("value", [-0.1, 1.1, "high", None])
def test_decision_rejects_bad_confidence(value: Any) -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(_decision(confidence=value))


def test_decision_title_normalized() -> None:
    decision = RoutingDecision.model_validate(_decision(title="  а   б \n в  " + "я" * 200))

    assert decision.title.startswith("а б в я")
    assert len(decision.title) == 80


def test_decision_rejects_too_many_candidates() -> None:
    candidates = [{"id": f"ws{i}", "score": 0.1} for i in range(21)]

    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(_decision(workspaces=candidates))


@pytest.mark.parametrize("score", [-1, 2])
def test_candidate_rejects_bad_score(score: float) -> None:
    with pytest.raises(ValidationError):
        WorkspaceCandidate.model_validate({"id": "demo", "score": score})
