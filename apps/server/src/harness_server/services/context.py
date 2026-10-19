"""Зависимости сервисов бота: фабрика сессий, адаптеры, workspace и владелец.

Собирается в wiring.py один раз на процесс (app или worker) и передаётся сервисам явно.
Тесты подставляют фейки без глобальных синглтонов (D-29).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.adapters.polza.protocol import Router
from harness_server.adapters.stt.protocol import SpeechToText
from harness_server.adapters.telegram.protocol import TelegramClient
from harness_server.config import WorkspaceConfig


@dataclass(frozen=True, slots=True, kw_only=True)
class BotContext:
    """Зависимости сервисов бота: сессии, адаптеры, workspace и владелец. Собирается в wiring.py."""

    session_factory: async_sessionmaker[AsyncSession]
    telegram: TelegramClient
    # None — STT не настроен: голосовые сообщения получают ответ «пришлите текстом».
    stt: SpeechToText | None
    workspaces: tuple[WorkspaceConfig, ...]
    owner_chat_id: int
    # Точные значения секретов для security/redaction: в Telegram не должны уйти.
    secret_values: tuple[str, ...]
    voice_max_bytes: int
    # None — Polza не настроена: работает запасной путь с кнопками всех workspace (D-13).
    router: Router | None = None
    # Порог ROUTING_MIN_CONFIDENCE: ниже — кнопки уточнения (D-33).
    routing_min_confidence: float = 0.6

    @property
    def known_workspace_ids(self) -> tuple[str, ...]:
        """Id всех workspace из harness.yaml в порядке конфига."""
        return tuple(workspace.id for workspace in self.workspaces)
