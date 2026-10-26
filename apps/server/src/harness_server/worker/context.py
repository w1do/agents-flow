"""Контекст диспетчера машины агента без подключения к серверной БД."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import SecretStr

from harness_server.adapters.sandbox import SandboxProvider
from harness_server.adapters.vault import McpSecretVault, SecretVault
from harness_server.config import HarnessConfig
from harness_server.worker.client import WorkerClient
from harness_server.worker.settings import WorkerSettings

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DispatchContext:
    provider: SandboxProvider
    config: HarnessConfig
    client: WorkerClient
    oauth_token: SecretStr
    agents_flow_url: str
    timeout_min: int
    poll_interval_sec: float
    secrets: tuple[str, ...] = field(default=())
    vault: SecretVault | None = None
    clock: Callable[[], datetime] = _utc_now
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def build_dispatch_context(
    settings: WorkerSettings, config: HarnessConfig, client: WorkerClient, provider: SandboxProvider
) -> DispatchContext | None:
    """Нет OAuth — нет запуска агента; HTTP-канал всё равно не требует ENV сервера."""
    if settings.claude_code_oauth_token is None:
        logger.warning("диспетчер песочницы не запущен: не задан CLAUDE_CODE_OAUTH_TOKEN")
        return None
    vault = None
    if settings.vault_mcp_url is not None and settings.vault_mcp_token is not None:
        vault = McpSecretVault(settings.vault_mcp_url, settings.vault_mcp_token)
    secrets = tuple(
        value.get_secret_value()
        for name in WorkerSettings.model_fields
        if isinstance(value := getattr(settings, name), SecretStr)
    )
    return DispatchContext(
        provider=provider,
        config=config,
        client=client,
        oauth_token=settings.claude_code_oauth_token,
        agents_flow_url=f"{settings.harness_public_url}/mcp",
        timeout_min=settings.agent_run_timeout_min,
        poll_interval_sec=settings.agent_poll_interval_sec,
        secrets=secrets,
        vault=vault,
    )
