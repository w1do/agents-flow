"""Чтение итога агента из песочницы: статус, событие result потока, состояние запуска (mvp-06,
design 3, 10, 13).

Чистые функции без БД и без провайдера: вход — текст файлов, выход — типизированный итог. Текст из
песочницы до этих функций проходит redaction (design 14); здесь секреты не обрабатываются.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

# Лимит текста из песочницы в лог и БД (design 14): хвост stderr и текст события не длиннее.
LOG_TEXT_LIMIT = 2000

# Итог Claude Code при исчерпанном лимите подписки (mvp-06, D-54): запуск завершается кодом 0 и
# subtype success, но работы не сделано, поэтому без распознавания задача стала бы готовой.
# Сравнение без регистра; префикс — начало итога после strip; «’» приводится к ASCII-апострофу.
# Длиннее LIMIT_TEXT_MAX_LEN символов итог не лимит: это сводка работы, а не сообщение CLI.
LIMIT_TEXT_MAX_LEN: Final = 300
LIMIT_TEXT_PREFIX: Final = "you've hit your"
LIMIT_MARKERS: Final = (
    "hit your session limit",
    "hit your usage limit",
    "usage limit reached",
)
# Машинная причина для задачи. Текст итога из песочницы в неё не попадает.
USAGE_LIMIT_REASON: Final = "usage_limit"


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
    # Исчерпан лимит подписки: см. LIMIT_MARKERS и _is_limit_result (D-54).
    limit_reached: bool = False


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
        """Агент завершился кодом 0; итог хода без ошибки и без признака исчерпанного лимита."""
        return (
            self.state is AgentState.FINISHED
            and self.exit_code == 0
            and self.result is not None
            and not self.result.is_error
            and not self.result.limit_reached
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
    text = event.get("result")
    is_error = event.get("is_error") is True
    turns = num_turns if isinstance(num_turns, int) else None
    return AgentResult(
        subtype=subtype if isinstance(subtype, str) else None,
        is_error=is_error,
        num_turns=turns,
        session_id=session_id if isinstance(session_id, str) else None,
        usage=usage if isinstance(usage, dict) else None,
        limit_reached=isinstance(text, str) and _is_limit_result(text, turns, is_error),
    )


def _is_limit_result(text: str, num_turns: int | None, is_error: bool) -> bool:
    """Лимит — только у короткого итога (один ход) или у итога с ошибкой. Длинный успешный ответ,
    который обсуждает лимиты, отказом агента не считается."""
    if not (is_error or (num_turns is not None and num_turns <= 1)):
        return False
    return _is_limit_text(text)


def _is_limit_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > LIMIT_TEXT_MAX_LEN:
        return False
    lowered = stripped.replace("’", "'").lower()
    if lowered.startswith(LIMIT_TEXT_PREFIX) and "limit" in lowered:
        return True
    return any(marker in lowered for marker in LIMIT_MARKERS)


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


LINUX_PID_MAX = 2**22


def parse_pid(pid_text: str) -> int | None:
    """pid из файла pid или stdout команды запуска. Пустое, нечисловое или вне диапазона — None.

    Только ASCII-цифры: str.isdigit() пропускает, например, «²», и int() на нём падает. Верхняя
    граница — максимум pid Linux (2**22): большее не влезает в колонку Integer и не может быть pid.
    pid ≤ 1 отвергается: `kill -0 -- -1` проверяет все процессы пользователя и всегда успешен,
    а 0 — группа самого вызывающего. Такой pid не может быть группой агента.
    """
    stripped = pid_text.strip()
    if not (stripped.isascii() and stripped.isdigit()):
        return None
    value = int(stripped)
    return value if 2 <= value <= LINUX_PID_MAX else None


def truncate_log_text(text: str) -> str:
    """Хвост текста не длиннее LOG_TEXT_LIMIT символов (design 14)."""
    return text[-LOG_TEXT_LIMIT:]
