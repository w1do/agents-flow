"""Чистые функции рендера Telegram: заголовки, строки этапов, callback_data и клавиатура."""

import pytest
from harness_server.adapters.telegram import InlineKeyboard
from harness_server.db.ids import uuid7
from harness_server.telegram.render import (
    STAGE_CHOOSING,
    TEXT_HELP,
    TEXT_NO_OPEN_TASKS,
    build_callback_data,
    build_clarify_callback,
    clarify_closed_text,
    clarify_keyboard,
    clarify_text,
    is_clarify_callback,
    parse_callback_data,
    parse_clarify_callback,
    render_card,
    render_status_report,
    short_title,
    stage_line,
    workspace_keyboard,
)
from harness_shared.projects import ProjectRepo, Workspace


def _workspace(workspace_id: str, name: str) -> Workspace:
    return Workspace(
        id=workspace_id,
        name=name,
        voice_aliases=[],
        repo=ProjectRepo(provider="gitlab", project="group/x"),
    )


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


def test_clarify_callback_roundtrip() -> None:
    routing_id = uuid7()

    for action in ("w", "s"):
        data = build_clarify_callback(routing_id, action)
        assert len(data.encode()) == 37
        assert parse_clarify_callback(data) == (routing_id, action)


@pytest.mark.parametrize(
    "data",
    ["rt:abc:w", "rt:{hex}:x", "ws:{hex}:demo", "rt:{hex}", "rt:{hex}:w:extra"],
)
def test_parse_clarify_rejects_garbage(data: str) -> None:
    data = data.replace("{hex}", uuid7().hex)

    assert parse_clarify_callback(data) is None


def test_is_clarify_callback() -> None:
    assert is_clarify_callback(build_clarify_callback(uuid7(), "w"))
    assert not is_clarify_callback(build_callback_data(uuid7(), "demo"))


def test_ws_parser_ignores_clarify_data() -> None:
    assert parse_callback_data(build_clarify_callback(uuid7(), "w")) is None


def test_clarify_keyboard_one_row_two_buttons() -> None:
    keyboard = clarify_keyboard(uuid7())

    assert len(keyboard.rows) == 1
    assert [button.text for button in keyboard.rows[0]] == ["Сделать задачу", "Показать статус"]


def test_clarify_texts() -> None:
    assert (
        clarify_text("сделай")
        == "Не уверен, что нужно: «сделай». Сделать задачу или показать статус?"
    )
    assert clarify_closed_text("сделай", "w") == "«сделай»: делаю задачу"
    assert clarify_closed_text("сделай", "s") == "«сделай»: показываю статус"


def test_render_status_report_format() -> None:
    text = render_status_report(
        [
            ("Демо-проект", [("добавь экспорт в CSV", "planning")]),
            ("Без проекта", [("сделай авторизацию по email", "choosing")]),
        ],
        total=2,
    )

    assert text == (
        "Открытые задачи: 2\n"
        "\n"
        "Демо-проект:\n"
        "• добавь экспорт в CSV — planning\n"
        "\n"
        "Без проекта:\n"
        "• сделай авторизацию по email — choosing"
    )


def test_render_status_report_limits_rows() -> None:
    rows = [(f"задача {i}", "new") for i in range(35)]

    text = render_status_report([("Демо-проект", rows)], total=35)

    assert text.count("• ") == 30
    assert text.endswith("… и ещё 5")


def test_render_status_report_empty() -> None:
    assert render_status_report([], total=0) == TEXT_NO_OPEN_TASKS
    assert TEXT_HELP.startswith("Не понял, вот что умею")
