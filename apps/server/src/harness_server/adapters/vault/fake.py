"""Фейк vault для тестов: заданные значения или заданная ошибка, без сети; журнал запросов."""

from collections.abc import Mapping

from pydantic import SecretStr

from harness_server.adapters.vault.errors import VaultError
from harness_server.vault_ref import VaultRef


class FakeVault:
    """Возвращает значение из values; ошибка fail бросается на каждом вызове. requested — журнал
    запрошенных ссылок (без значений)."""

    def __init__(
        self,
        values: Mapping[VaultRef, str] | None = None,
        *,
        fail: VaultError | None = None,
    ) -> None:
        self.values = dict(values or {})
        self.fail = fail
        self.requested: list[VaultRef] = []

    async def get(self, ref: VaultRef) -> SecretStr:
        self.requested.append(ref)
        if self.fail is not None:
            raise self.fail
        value = self.values.get(ref)
        if value is None:
            raise VaultError("unavailable", ref=f"{ref.service}/{ref.name}")
        return SecretStr(value)
