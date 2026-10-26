"""Зависимости сервисов бота: фабрика сессий, адаптеры, проекты и владелец.

Собирается в wiring.py один раз на процесс (app или worker) и передаётся сервисам явно.
Тесты подставляют фейки без глобальных синглтонов (D-29).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from harness_shared.projects import Workspace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.adapters.polza.protocol import Router
from harness_server.adapters.stt.protocol import SpeechToText
from harness_server.adapters.telegram.protocol import TelegramClient

# Источник активных проектов. В проде читает таблицу projects (project-catalog); тесты подставляют
# фиксированный кортеж. Каждый вызов даёт свежие данные: новый проект виден без рестарта.
WorkspaceSource = Callable[[], Awaitable[tuple[Workspace, ...]]]


@dataclass(frozen=True, slots=True, kw_only=True)
class BotContext:
    """Зависимости сервисов бота: сессии, адаптеры, проекты и владелец. Собирается в wiring.py."""

    session_factory: async_sessionmaker[AsyncSession]
    telegram: TelegramClient
    # None — STT не настроен: голосовые сообщения получают ответ «пришлите текстом».
    stt: SpeechToText | None
    load_workspaces: WorkspaceSource
    owner_chat_id: int
    # Точные значения секретов для security/redaction: в Telegram не должны уйти.
    secret_values: tuple[str, ...]
    voice_max_bytes: int
    # None — Polza не настроена: работает запасной путь с кнопками всех проектов (D-13).
    router: Router | None = None
    # Порог ROUTING_MIN_CONFIDENCE: ниже — кнопки уточнения (D-33).
    routing_min_confidence: float = 0.6

    async def workspaces(self) -> tuple[Workspace, ...]:
        """Активные проекты в порядке id. Отключённые не предлагаются и не принимают задачи."""
        return await self.load_workspaces()

    async def known_workspace_ids(self) -> tuple[str, ...]:
        """Id активных проектов: проверка workspace_id при создании и выборе задачи."""
        return tuple(workspace.id for workspace in await self.load_workspaces())
