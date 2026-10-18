"""Чистые функции рендера Telegram: заголовки, строки этапов, callback_data и клавиатура."""

import pytest
from harness_server.adapters.telegram import InlineKeyboard
from harness_server.config import WorkspaceConfig
from harness_server.db.ids import uuid7
from harness_server.telegram.render import (
    STAGE_CHOOSING,
    build_callback_data,
    parse_callback_data,
    render_card,
    short_title,
    stage_line,
    workspace_keyboard,
)


def _workspace(workspace_id: str, name: str) -> WorkspaceConfig:
    return WorkspaceConfig(id=workspace_id, name=name, voice_aliases=[], gitlab_project="group/x")


def test_short_title_keeps_short_text() -> None:
    assert short_title("добавь экспорт") == "добавь экспорт"


def test_short_title_truncates_to_40() -> None:
    title = short_title("а" * 60)

    assert len(title) == 40
    assert title.endswith("…")


def test_short_title_uses_first_non_empty_line() -> None:
    assert short_title("\n\n  первая   строка \nвторая") == "первая строка"


def test_stage_line_format() -> None:
    assert stage_line("добавь экспорт", STAGE_CHOOSING) == (
        "Задача [добавь экспорт] (выберите проект)"
    )


def test_callback_data_roundtrip() -> None:
    task_id = uuid7()

    data = build_callback_data(task_id, "demo")

    assert parse_callback_data(data) == (task_id, "demo")


def test_callback_data_max_length_ok() -> None:
    data = build_callback_data(uuid7(), "a" * 28)

    assert len(data.encode()) == 64


def test_callback_data_too_long_raises() -> None:
    with pytest.raises(ValueError):
        build_callback_data(uuid7(), "a" * 29)


@pytest.mark.parametrize(
    "data",
    [
        "ws:abc:demo",
        "xx:" + "0" * 32 + ":demo",
        "ws:" + "0" * 32 + ":",
        "ws",
    ],
)
def test_parse_callback_data_rejects_garbage(data: str) -> None:
    assert parse_callback_data(data) is None


def test_render_card_limits_length() -> None:
    card = render_card("а" * 5000, ["строка"])

    assert len(card) <= 4096
    assert card.endswith("строка")


def test_workspace_keyboard_one_button_per_workspace() -> None:
    task_id = uuid7()

    keyboard = workspace_keyboard(
        task_id, [_workspace("demo", "Демо"), _workspace("shop", "Магазин")]
    )

    assert isinstance(keyboard, InlineKeyboard)
    assert [[button.text for button in row] for row in keyboard.rows] == [["Демо"], ["Магазин"]]
    assert keyboard.rows[1][0].callback_data == build_callback_data(task_id, "shop")
