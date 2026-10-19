"""Контракт пайплайна задачи для диспетчера (mvp-06, design 11).

Пайплайн описывает, какую задачу брать из очереди, в каком статусе её оставить и что делать в
песочнице.
Реальные пайплайны (plan, implement) появятся в mvp-08/09; реестр PIPELINES в mvp-06 пуст.
Пайплайн не работает с БД и песочницей напрямую: только через AgentRunner, который выдаёт диспетчер.
"""

from dataclasses import dataclass
from typing import Final, Protocol

from harness_shared.sandboxes import AgentRole
from harness_shared.tasks import TaskKind, TaskStatus

from harness_server.config import HarnessConfig
from harness_server.db.models import Task
from harness_server.services.agent_result import AgentRun
from harness_server.services.sandboxes import AgentStart


@dataclass(frozen=True, slots=True)
class Outcome:
    """Итог пайплайна. ok=False переводит задачу в error с причиной reason (design 11)."""

    ok: bool
    reason: str | None = None
    text: str | None = None


class AgentRunner(Protocol):
    """Что пайплайн может сделать с агентом: запустить и дождаться итога. Выдаётся диспетчером."""

    async def run_agent(self, prompt: str) -> AgentStart:
        """Запускает агента с prompt (идемпотентно, см. services/sandboxes.run_agent)."""
        ...

    async def wait_agent(self) -> AgentRun:
        """Опрашивает агента с интервалом AGENT_POLL_INTERVAL_SEC до терминального состояния."""
        ...


class Pipeline(Protocol):
    """Пайплайн одного kind. Свойства только для чтения: реализации не обязаны хранить их как
    поля."""

    @property
    def kind(self) -> TaskKind: ...

    @property
    def from_status(self) -> TaskStatus: ...

    @property
    def to_status(self) -> TaskStatus | None:
        """None — задача берётся без смены статуса (план остаётся в planning до mvp-08)."""
        ...

    @property
    def role(self) -> AgentRole: ...

    def base_ref(self, task: Task, config: HarnessConfig) -> str:
        """Базовая ветка для worktree задачи."""
        ...

    async def run(self, runner: AgentRunner, task: Task) -> Outcome:
        """Выполняет этап задачи через runner. Исключение равнозначно ok=False."""
        ...


# Реестр пуст в mvp-06: тесты передают свой реестр в dispatch_once, mvp-08/09 добавят пайплайны
# сюда.
PIPELINES: Final[dict[TaskKind, Pipeline]] = {}
