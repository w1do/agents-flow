"""Ссылка на секрет в vault: `vault:<project>/<service>/<name>` (D-45).

Ссылка — не секрет: она лежит в конфиге, в базе проектов и в ENV. Значение берётся из vault только в
момент использования и в файлы не пишется. Части ссылки не содержат «/» и не начинаются и не
кончаются пробелом; внутри части допускаются пробелы и кириллица. Живёт в shared, потому что
модели проекта проверяют access_ref до записи (project-catalog).
"""

import re
from dataclasses import dataclass

_PART = r"[^/\s](?:[^/\r\n]*[^/\s])?"
_VAULT_REF_RE = re.compile(rf"vault:({_PART})/({_PART})/({_PART})")


@dataclass(frozen=True, slots=True)
class VaultRef:
    """Разобранная ссылка на секрет: проект, сервис и имя записи в vault."""

    project: str
    service: str
    name: str

    def __str__(self) -> str:
        return f"vault:{self.project}/{self.service}/{self.name}"


def parse_vault_ref(text: str) -> VaultRef | None:
    """Разбирает ссылку vault:<project>/<service>/<name>. Не ссылка (нет префикса, не три части,
    пустая часть) — None: вызывающий решает, что это значит (ошибка конфига или ENV-значение)."""
    match = _VAULT_REF_RE.fullmatch(text)
    if match is None:
        return None
    return VaultRef(project=match.group(1), service=match.group(2), name=match.group(3))


def is_vault_ref(text: str) -> bool:
    """True, если текст — корректная ссылка на секрет в vault."""
    return parse_vault_ref(text) is not None
