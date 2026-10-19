"""Композиционный корень бота: httpx-клиент, адаптеры и BotContext из настроек (D-29).

Здесь и только здесь создаются реализации адаптеров. Сервисы, API и worker получают готовые
объекты, а тесты подставляют фейки через параметр adapters, без глобальных синглтонов.
"""

from dataclasses import dataclass

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harness_server.adapters.novita import NovitaSandboxProvider, SandboxProvider
from harness_server.adapters.polza import POLZA_API_URL, PolzaRouter, Router
from harness_server.adapters.stt import OpenAiCompatibleStt, SpeechToText
from harness_server.adapters.telegram import HttpxTelegramClient, TelegramClient
from harness_server.adapters.vault import McpSecretVault, SecretVault
from harness_server.config import HarnessConfig
from harness_server.services.context import BotContext
from harness_server.settings import Settings

# Соединение должно открываться быстро; ответ Bot API может идти дольше, поэтому таймауты разные.
_HTTP_TIMEOUT_SEC = 30.0
_HTTP_CONNECT_TIMEOUT_SEC = 10.0


@dataclass(frozen=True, slots=True)
class BotAdapters:
    """Адаптеры внешних API. stt = None, если распознавание не настроено."""

    telegram: TelegramClient
    stt: SpeechToText | None
    # router = None, если Polza не настроена (POLZA_AI_KEY и POLZA_AI_MODEL).
    router: Router | None = None


def build_http_client() -> httpx.AsyncClient:
    """Общий httpx-клиент процесса. Закрывается вызывающим (lifespan app или worker)."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_HTTP_TIMEOUT_SEC, connect=_HTTP_CONNECT_TIMEOUT_SEC)
    )


def build_adapters(settings: Settings, http: httpx.AsyncClient) -> BotAdapters:
    """Реальные адаптеры из настроек. STT и маршрутизатор — только при заданных ключе и модели."""
    telegram = HttpxTelegramClient(settings.telegram_bot_token.get_secret_value(), http)
    stt: SpeechToText | None = None
    if settings.stt_api_url and settings.stt_api_key is not None and settings.stt_model:
        stt = OpenAiCompatibleStt(
            settings.stt_api_url,
            settings.stt_api_key.get_secret_value(),
            settings.stt_model,
            http,
        )
    router: Router | None = None
    if settings.polza_ai_key is not None and settings.polza_ai_model:
        router = PolzaRouter(
            settings.polza_ai_url or POLZA_API_URL,
            settings.polza_ai_key.get_secret_value(),
            settings.polza_ai_model,
            http,
        )
    return BotAdapters(telegram=telegram, stt=stt, router=router)


def build_sandbox_provider(settings: Settings) -> SandboxProvider | None:
    """Провайдер песочницы Novita из настроек; None, если NOVITA_API_KEY не задан (песочница не
    настроена)."""
    if settings.novita_api_key is None:
        return None
    return NovitaSandboxProvider(
        api_key=settings.novita_api_key.get_secret_value(),
        domain=settings.novita_domain,
    )


def build_vault(settings: Settings) -> SecretVault | None:
    """Vault из настроек; None, если VAULT_MCP_URL или VAULT_MCP_TOKEN не заданы.

    Без vault ссылки vault:… в harness.yaml не разрешаются: сервис получает not_configured.
    """
    if settings.vault_mcp_url is None or settings.vault_mcp_token is None:
        return None
    return McpSecretVault(settings.vault_mcp_url, settings.vault_mcp_token)


def secret_values(settings: Settings) -> tuple[str, ...]:
    """Значения всех SecretStr из настроек: их не должно быть в тексте, уходящем в Telegram."""
    values: list[str] = []
    for name in Settings.model_fields:
        value = getattr(settings, name)
        if isinstance(value, SecretStr):
            values.append(value.get_secret_value())
    return tuple(values)


def build_bot_context(
    settings: Settings,
    config: HarnessConfig,
    session_factory: async_sessionmaker[AsyncSession],
    adapters: BotAdapters,
) -> BotContext:
    """Контекст сервисов бота: владелец из TELEGRAM_CHAT_ID, workspace из harness.yaml."""
    return BotContext(
        session_factory=session_factory,
        telegram=adapters.telegram,
        stt=adapters.stt,
        workspaces=tuple(config.workspaces),
        owner_chat_id=int(settings.telegram_chat_id),
        secret_values=secret_values(settings),
        voice_max_bytes=settings.voice_max_bytes,
        router=adapters.router,
        routing_min_confidence=settings.routing_min_confidence,
    )
