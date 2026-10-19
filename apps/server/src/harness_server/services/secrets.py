"""Разрешение ссылок на секреты: vault:… из harness.yaml или значение из ENV (D-45, design 1).

Значения возвращаются вызывающему и живут только в памяти процесса: в логи, файлы и исключения
не попадают. Ошибка vault пробрасывается как VaultError с причиной, без значения.
"""

from pydantic import SecretStr

from harness_server.adapters.vault import SecretVault, VaultError
from harness_server.vault_ref import parse_vault_ref


async def resolve(
    vault: SecretVault | None,
    ref: str | None,
    *,
    fallback: SecretStr | None,
) -> SecretStr | None:
    """Значение секрета по ссылке; без ссылки — fallback (обычно ENV).

    ref None — вернуть fallback, vault не нужен. Ссылка есть, а vault не настроен — VaultError
    not_configured: тихо подменять ссылку на fallback нельзя, иначе ключ незаметно уйдёт не тот.
    """
    if ref is None:
        return fallback
    if vault is None:
        raise VaultError("not_configured")
    parsed = parse_vault_ref(ref)
    if parsed is None:
        # Конфиг уже проверен при загрузке; сюда попадают только ссылки, собранные в обход него.
        raise VaultError("not_configured")
    return await vault.get(parsed)
