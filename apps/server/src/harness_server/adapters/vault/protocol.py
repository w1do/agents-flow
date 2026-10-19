"""Протокол доступа к секретам vault. Сервисы зависят от него, а не от MCP-клиента (D-45)."""

from typing import Protocol

from pydantic import SecretStr

from harness_server.vault_ref import VaultRef


class SecretVault(Protocol):
    """Выдаёт значение секрета по ссылке. Кэша нет: каждый вызов — запрос к vault."""

    async def get(self, ref: VaultRef) -> SecretStr:
        """Значение записи vault. Бросает VaultError с причиной (см. errors.py)."""
        ...
