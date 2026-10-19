"""Клиент vault по MCP (Streamable HTTP, официальный Python SDK, D-45).

Единственный модуль, который импортирует `mcp` и `httpx2`. Каждый `get` открывает сессию заново:
сервер не держит состояние между командами, а ключ нужен редко (bootstrap, активация, запуск).
Текст ошибок содержит только причину и service/name: ни значения, ни URL, ни токена.
"""

import asyncio
import json
from typing import Final

import httpx2
import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from harness_server.adapters.vault.errors import VaultError
from harness_server.vault_ref import VaultRef

# Общий дедлайн на один get: сеть, initialize и вызов инструмента. Дольше — задача не должна висеть.
VAULT_TIMEOUT_SEC: Final = 30
# Имя инструмента и поле с секретом — по решению владельца (proposal, открытый вопрос 1).
_TOOL_NAME: Final = "get_credential"
_SECRET_FIELD: Final = "secret"


def parse_credential(result: types.CallToolResult, label: str) -> SecretStr:
    """Значение секрета из ответа get_credential.

    Сначала structuredContent (поле secret), затем первый текстовый блок как JSON-объект с полем
    secret. Иначе — invalid_response. label (service/name) попадает только в текст ошибки.
    """
    structured = result.structured_content
    if isinstance(structured, dict):
        value = structured.get(_SECRET_FIELD)
        if isinstance(value, str) and value:
            return SecretStr(value)
    for block in result.content:
        if not isinstance(block, types.TextContent):
            continue
        try:
            payload = json.loads(block.text)
        except ValueError:
            break
        value = payload.get(_SECRET_FIELD) if isinstance(payload, dict) else None
        if isinstance(value, str) and value:
            return SecretStr(value)
        break
    raise VaultError("invalid_response", ref=label)


def _leaves(exc: BaseException) -> list[BaseException]:
    """Листья исключения. Ошибки, вышедшие из task group anyio, приходят группой: разворачиваем."""
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for sub in exc.exceptions:
            leaves.extend(_leaves(sub))
        return leaves
    return [exc]


# Эти исключения означают отмену или выход процесса: их нельзя превращать в ошибку vault.
_FATAL: Final = (asyncio.CancelledError, KeyboardInterrupt, SystemExit)


def _is_fatal(exc: BaseException) -> bool:
    """True, если среди листьев есть отмена или выход процесса; такое исключение пробрасывается."""
    return any(isinstance(leaf, _FATAL) for leaf in _leaves(exc))


def _transport_error(exc: BaseException, label: str) -> VaultError:
    """Сбой транспорта или протокола: таймаут (встроенный или httpx) — timeout, остальное —
    unavailable. MCPError (в т. ч. HTTP 401 и 5xx) — unavailable: это не ошибка инструмента.

    Сообщение исходного исключения не копируется: в нём могут быть URL и текст ответа сервера.
    """
    leaves = _leaves(exc)
    if any(isinstance(leaf, (TimeoutError, httpx2.TimeoutException)) for leaf in leaves):
        return VaultError("timeout", ref=label)
    return VaultError("unavailable", ref=label)


class McpSecretVault:
    """SecretVault поверх MCP-сервера vault. url — https, token — Bearer-токен для сервера."""

    def __init__(self, url: str, token: SecretStr, *, timeout_s: float = VAULT_TIMEOUT_SEC) -> None:
        self._url = url
        self._token = token
        self._timeout_s = timeout_s

    async def get(self, ref: VaultRef) -> SecretStr:
        """Значение записи ref. Бросает VaultError: причина timeout, unavailable и т. д."""
        label = f"{ref.service}/{ref.name}"
        try:
            async with asyncio.timeout(self._timeout_s):
                raw = await self._call(ref)
        except BaseExceptionGroup as group:
            if _is_fatal(group):
                raise
            raise _transport_error(group, label) from None
        except Exception as exc:
            raise _transport_error(exc, label) from None
        if not isinstance(raw, types.CallToolResult):
            raise VaultError("invalid_response", ref=label)
        if raw.is_error:
            raise VaultError("tool_error", ref=label)
        return parse_credential(raw, label)

    async def _call(
        self, ref: VaultRef
    ) -> types.CallToolResult | types.InputRequiredResult | types.Result:
        # Заголовок задаётся на клиенте HTTP: SDK не принимает headers как аргумент. Клиент создан
        # здесь, поэтому закрывается здесь (SDK закрывает только свои клиенты).
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        timeout = httpx2.Timeout(self._timeout_s)
        arguments = {"project": ref.project, "service": ref.service, "name": ref.name}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=timeout) as http,
            streamable_http_client(self._url, http_client=http) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool(_TOOL_NAME, arguments)
