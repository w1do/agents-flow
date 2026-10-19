"""Чтение итога агента из песочницы: статус, событие result потока, состояние запуска (mvp-06,
design 3, 10, 13).

Чистые функции без БД и без провайдера: вход — текст файлов, выход — типизированный итог. Текст из
песочницы до этих функций проходит redaction (design 14); здесь секреты не обрабатываются.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Лимит текста из песочницы в лог и БД (design 14): хвост stderr и текст события не длиннее.
LOG_TEXT_LIMIT = 2000


class AgentState(StrEnum):
    """Состояние запуска агента, которое видит сервер."""

    RUNNING = "running"
    FINISHED = "finished"
    TIMED_OUT = "timed_out"
    DIED = "died"


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Итог хода из события type == "result" потока stream-json (D-37)."""

    subtype: str | None
    is_error: bool
    num_turns: int | None
    session_id: str | None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Итог опроса агента. reason — машинная причина без текста песочницы; stderr_tail уже
    redacted."""

    state: AgentState
    exit_code: int | None = None
    result: AgentResult | None = None
    reason: str | None = None
    stderr_tail: str = ""

    @property
    def succeeded(self) -> bool:
        """Агент завершился кодом 0 и итог хода не помечен ошибкой."""
        return (
            self.state is AgentState.FINISHED
            and self.exit_code == 0
            and self.result is not None
            and not self.result.is_error
        )


def parse_result(lines: Sequence[str]) -> AgentResult | None:
    """Ищет последнее событие type == "result" среди строк потока. Битые строки пропускаются.

    Идёт с конца: итог хода — последнее событие потока. Нет события — None.
    """
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        return _build_result(event)
    return None


def _build_result(event: dict[str, Any]) -> AgentResult:
    subtype = event.get("subtype")
    num_turns = event.get("num_turns")
    session_id = event.get("session_id")
    usage = event.get("usage")
    return AgentResult(
        subtype=subtype if isinstance(subtype, str) else None,
        is_error=event.get("is_error") is True,
        num_turns=num_turns if isinstance(num_turns, int) else None,
        session_id=session_id if isinstance(session_id, str) else None,
        usage=usage if isinstance(usage, dict) else None,
    )


def parse_exit_code(status_text: str) -> int | None:
    """Код выхода из status.json ({"exit_code": N, ...}). Битый файл или нет числа — None."""
    try:
        data = json.loads(status_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    code = data.get("exit_code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def parse_pid(pid_text: str) -> int | None:
    """pid из файла pid. Пустой или нечисловой файл — None (процесс считается не запущенным)."""
    stripped = pid_text.strip()
    if not stripped.isdigit():
        return None
    value = int(stripped)
    return value if value > 0 else None


def truncate_log_text(text: str) -> str:
    """Хвост текста не длиннее LOG_TEXT_LIMIT символов (design 14)."""
    return text[-LOG_TEXT_LIMIT:]
