"""Входные данные отчётов worker; токен задачи передаётся отдельным заголовком."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from harness_shared.tasks import TaskStatus, TaskText, TestsState

EventKey = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_key: EventKey
    text: TaskText


class StatusIn(EventIn):
    status: TaskStatus


class CheckpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_key: EventKey
    summary: TaskText
    files: list[Annotated[str, StringConstraints(max_length=4096)]] = Field(
        default_factory=list, max_length=1000
    )
    diff_redacted: Annotated[str, StringConstraints(max_length=200_000)] | None = None
    next_step: TaskText | None = None
    status: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    tokens: int | None = Field(default=None, ge=0)


class ResultIn(EventIn):
    branch: Annotated[str, StringConstraints(max_length=255)] | None = None
    mr_url: Annotated[str, StringConstraints(max_length=4096)] | None = None
    tests_state: TestsState = TestsState.NOT_RUN
