"""Разбор записанных апдейтов Telegram в нормализованные входящие события."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from harness_server.telegram.parse import (
    ButtonPress,
    IncomingText,
    IncomingVoice,
    dedup_key,
    dump_incoming,
    load_incoming,
    parse_update,
)

Loader = Callable[[str], dict[str, Any]]


def test_parse_text_message(telegram_update: Loader) -> None:
    incoming = parse_update(telegram_update("text_message"))

    assert incoming == IncomingText(
        update_id=10001, chat_id=424242, message_id=501, text="добавь экспорт в CSV"
    )


def test_parse_voice_message(telegram_update: Loader) -> None:
    incoming = parse_update(telegram_update("voice_message"))

    assert incoming == IncomingVoice(
        update_id=10002,
        chat_id=424242,
        message_id=502,
        file_id="VOICE_FILE_1",
        duration=3,
        mime_type="audio/ogg",
        file_size=2048,
    )


def test_parse_removes_nul_from_text(telegram_update: Loader) -> None:
    # NUL не принимают JSONB и TEXT Postgres: символ удаляется до сохранения (S2b).
    raw = telegram_update("text_message")
    raw["message"]["text"] = "при\x00вет\x00"

    incoming = parse_update(raw)

    assert incoming == IncomingText(update_id=10001, chat_id=424242, message_id=501, text="привет")


def test_text_of_only_nul_is_ignored(telegram_update: Loader) -> None:
    raw = telegram_update("text_message")
    raw["message"]["text"] = "\x00 \x00"

    assert parse_update(raw) is None


def test_parse_callback_query(telegram_update: Loader) -> None:
    incoming = parse_update(telegram_update("callback_query"))

    assert incoming == ButtonPress(
        update_id=10003,
        callback_query_id="4242000000000000001",
        chat_id=424242,
        message_id=100,
        data="ws:00000000000000000000000000000000:demo",
    )


def test_parse_foreign_chat_keeps_chat_id(telegram_update: Loader) -> None:
    # Парсер не фильтрует чаты: это делает webhook. Здесь chat_id должен сохраниться как есть.
    incoming = parse_update(telegram_update("foreign_chat_message"))

    assert incoming is not None
    assert incoming.chat_id == 999


@pytest.mark.parametrize(
    "case",
    ["edited_message", "start_command", "empty", "not_a_dict", "callback_without_data"],
)
def test_unsupported_updates_return_none(telegram_update: Loader, case: str) -> None:
    raw: object
    if case == "empty":
        raw = {}
    elif case == "not_a_dict":
        raw = "not a dict"
    elif case == "callback_without_data":
        update = telegram_update("callback_query")
        del update["callback_query"]["data"]
        raw = update
    else:
        raw = telegram_update(case)

    assert parse_update(raw) is None


def test_dump_and_load_roundtrip(telegram_update: Loader) -> None:
    for name in ("text_message", "voice_message", "callback_query"):
        incoming = parse_update(telegram_update(name))
        assert incoming is not None

        payload = dump_incoming(incoming)
        # Через JSON: в колонке JSONB payload проходит именно такой путь.
        restored = load_incoming(json.loads(json.dumps(payload)))

        assert restored == incoming


@pytest.mark.parametrize("payload", [None, {"type": "x"}])
def test_load_incoming_invalid_returns_none(payload: object) -> None:
    assert load_incoming(payload) is None


def test_dedup_key(telegram_update: Loader) -> None:
    text = parse_update(telegram_update("text_message"))
    button = parse_update(telegram_update("callback_query"))
    assert text is not None
    assert button is not None

    assert dedup_key(text) == ("update", "10001")
    assert dedup_key(button) == ("callback", "4242000000000000001")


def test_payload_has_no_sender_fields(telegram_update: Loader) -> None:
    incoming = parse_update(telegram_update("text_message"))
    assert incoming is not None

    payload = dump_incoming(incoming)

    assert "from" not in payload
    assert "first_name" not in json.dumps(payload, ensure_ascii=False)
