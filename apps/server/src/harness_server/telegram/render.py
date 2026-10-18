"""Тексты бота и сборка сообщений Telegram: чистые функции без I/O и без БД.

Все тексты, которые видит владелец, собраны здесь, чтобы спецификация и тесты сверялись с одним
местом.
Строки этапов — `Задача [<название>] (<этап>)`: одно сообщение на задачу дописывается новыми
строками
(D-28, решение 9 design.md).
"""

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from harness_server.adapters.telegram.types import InlineButton, InlineKeyboard
from harness_server.config import WorkspaceConfig

STAGE_CHOOSING: Final = "выберите проект"
TEXT_STT_FAILED: Final = "не удалось распознать, пришлите текстом"
TEXT_ALREADY_CHOSEN: Final = "проект уже выбран"
TEXT_UNKNOWN_PROJECT: Final = "проект не найден"
TEXT_TASK_NOT_FOUND: Final = "задача не найдена"
TEXT_BAD_BUTTON: Final = "кнопка устарела"
CALLBACK_PREFIX: Final = "ws"
MAX_CALLBACK_BYTES: Final = 64
MAX_MESSAGE_LEN: Final = 4096
SHORT_TITLE_LEN: Final = 40
CARD_TEXT_LEN: Final = 1000
_TASK_HEX_LEN: Final = 32


def planning_stage(workspace_name: str) -> str:
    """Этап после выбора проекта: «проект «<name>», планирование»."""
    return f"проект «{workspace_name}», планирование"


def short_title(text: str) -> str:
    """Краткое название задачи: первая непустая строка с схлопнутыми пробелами, не длиннее 40
    символов."""
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if not collapsed:
            continue
        if len(collapsed) <= SHORT_TITLE_LEN:
            return collapsed
        return collapsed[: SHORT_TITLE_LEN - 1].rstrip() + "…"
    return ""


def stage_line(title: str, stage: str) -> str:
    """Строка этапа в сообщении задачи."""
    return f"Задача [{title}] ({stage})"


def render_card(text: str, lines: Sequence[str]) -> str:
    """Сообщение задачи: текст задачи, пустая строка и строки этапов.

    Текст и весь результат ограничены лимитами Telegram, чтобы сообщение не отвергалось целиком.
    """
    body = text.strip()
    if len(body) > CARD_TEXT_LEN:
        body = body[: CARD_TEXT_LEN - 1].rstrip() + "…"
    result = "\n".join([body, "", *lines])
    if len(result) > MAX_MESSAGE_LEN:
        result = result[: MAX_MESSAGE_LEN - 1] + "…"
    return result


def build_callback_data(task_id: UUID, workspace_id: str) -> str:
    """callback_data кнопки: `ws:<task.id.hex>:<workspace_id>` (D-28).

    Бросает ValueError, если результат длиннее 64 байт: id workspace проверяется в конфиге заранее.
    """
    data = f"{CALLBACK_PREFIX}:{task_id.hex}:{workspace_id}"
    if len(data.encode()) > MAX_CALLBACK_BYTES:
        raise ValueError("callback_data длиннее 64 байт")
    return data


def parse_callback_data(data: str) -> tuple[UUID, str] | None:
    """Разбирает callback_data. None — формат не наш или id задачи не UUID: данные от клиента не
    доверены."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    task_hex, workspace_id = parts[1], parts[2]
    if len(task_hex) != _TASK_HEX_LEN or workspace_id == "":
        return None
    try:
        task_id = UUID(hex=task_hex)
    except ValueError:
        return None
    return task_id, workspace_id


def workspace_keyboard(task_id: UUID, workspaces: Sequence[WorkspaceConfig]) -> InlineKeyboard:
    """Кнопки выбора проекта: по одной в ряд, в порядке harness.yaml."""
    return InlineKeyboard(
        rows=tuple(
            (
                InlineButton(
                    text=workspace.name,
                    callback_data=build_callback_data(task_id, workspace.id),
                ),
            )
            for workspace in workspaces
        )
    )
