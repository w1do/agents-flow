"""Ссылка на секрет в vault: разбор вынесен в harness_shared.vault_ref (D-45).

Реэкспорт оставлен, чтобы сервер импортировал ссылки из одного места; правила живут в shared,
потому что модели проекта проверяют access_ref до записи.
"""

from harness_shared.vault_ref import VaultRef, is_vault_ref, parse_vault_ref

__all__ = ["VaultRef", "is_vault_ref", "parse_vault_ref"]
