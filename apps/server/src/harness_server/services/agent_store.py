"""Порт серверного учёта агента для локальных операций запуска и очистки."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from harness_shared.worker_sandbox import AgentRunInfo
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


class AgentStore(Protocol):
    """Локальные команды не знают, хранит состояние ORM или HTTP-адаптер."""

    async def info(self) -> AgentRunInfo: ...
    async def record_pid(self, pid: int) -> None: ...
    async def record_started(self, started_at: datetime) -> bool: ...
    async def issue_token(
        self, task_id: UUID, secret_key: SecretStr | None, timeout_min: int, now: datetime
    ) -> str: ...
    async def revoke_tokens(self, task_id: UUID) -> None: ...
    async def mark_error(self) -> None: ...


class SqlAgentStore:
    """ORM-реализация для существующих серверных команд и контрактных тестов песочницы."""

    def __init__(self, session: AsyncSession, provider_id: str) -> None:
        self.session = session
        self.provider_id = provider_id

    async def info(self) -> AgentRunInfo:
        """Читает время и pid из серверной записи."""
        from harness_server.services.sandboxes import agent_run_info

        return await agent_run_info(self.session, self.provider_id)

    async def record_pid(self, pid: int) -> None:
        """Сохраняет подтверждённый pid группы агента."""
        from harness_server.services.sandboxes import record_agent_pid

        await record_agent_pid(self.session, self.provider_id, pid)

    async def record_started(self, started_at: datetime) -> bool:
        """Фиксирует начало отсчёта до команды запуска."""
        from harness_server.services.sandboxes import _record_agent_started

        await _record_agent_started(self.session, self.provider_id, started_at)
        return True

    async def issue_token(
        self, task_id: UUID, secret_key: SecretStr | None, timeout_min: int, now: datetime
    ) -> str:
        """Выдаёт токен роли, сохраняя только его хеш."""
        from harness_server.services.sandboxes import issue_task_token

        assert secret_key is not None
        return await issue_task_token(
            self.session,
            task_id,
            secret_key=secret_key.get_secret_value(),
            agent_run_timeout_min=timeout_min,
            now=now,
        )

    async def revoke_tokens(self, task_id: UUID) -> None:
        """Отзывает токены первым шагом очистки."""
        from harness_server.services.sandboxes import revoke_task_tokens

        await revoke_task_tokens(self.session, task_id)

    async def mark_error(self) -> None:
        """Сохраняет закрепление для разбора ошибки очистки."""
        from harness_shared.sandboxes import SandboxStatus

        from harness_server.services.sandboxes import _locked_sandbox

        row = await _locked_sandbox(self.session, self.provider_id)
        row.status = SandboxStatus.ERROR
        await self.session.commit()


def agent_store(value: AsyncSession | AgentStore, provider_id: str) -> AgentStore:
    """Выбор порта на сервере; worker всегда передаёт реализацию HTTP."""
    return SqlAgentStore(value, provider_id) if isinstance(value, AsyncSession) else value
