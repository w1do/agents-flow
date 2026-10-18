"""Разбор апдейтов Telegram в нормализованные входящие события.

Чистая функция: без I/O и без БД. Фильтр чужих чатов здесь не нужен: его делает webhook, а парсер
возвращает chat_id как есть. Модели Telegram внутренние (D-29), в shared/ ничего не добавляется.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

UpdateKind = Literal["update", "callback"]

# Telegram ограничивает callback_query.id 64 символами; длиннее — апдейт не от Telegram.
_MAX_CALLBACK_QUERY_ID = 64


class _Chat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int


class _Voice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str
    file_unique_id: str
    duration: int
    mime_type: str | None = None
    file_size: int | None = None


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message_id: int
    chat: _Chat
    text: str | None = None
    voice: _Voice | None = None


class _CallbackQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    data: str | None = None
    message: _Message | None = None


class _Update(BaseModel):
    """Верхний уровень апдейта. Поля отправителя (from) игнорируются и не попадают дальше."""

    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: _Message | None = None
    callback_query: _CallbackQuery | None = None


class IncomingText(BaseModel):
    """Текст владельца: станет текстом задачи."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["text"] = "text"
    update_id: int
    chat_id: int
    message_id: int
    text: str


class IncomingVoice(BaseModel):
    """Голосовое сообщение владельца: распознаётся STT перед созданием задачи."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["voice"] = "voice"
    update_id: int
    chat_id: int
    message_id: int
    file_id: str
    duration: int
    mime_type: str | None = None
    file_size: int | None = None


class ButtonPress(BaseModel):
    """Нажатие инлайн-кнопки: callback_data несёт задачу и выбранный workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["button"] = "button"
    update_id: int
    callback_query_id: str
    chat_id: int
    message_id: int
    data: str


Incoming = Annotated[IncomingText | IncomingVoice | ButtonPress, Field(discriminator="type")]
_INCOMING: TypeAdapter[Incoming] = TypeAdapter(Incoming)


def parse_update(raw: object) -> Incoming | None:
    """Разбирает апдейт Telegram. None — апдейт не поддерживается и его не нужно обрабатывать.

    Не поддерживаются: команды «/…» (mvp-05), правки сообщений, стикеры, фото и другие типы.
    """
    try:
        update = _Update.model_validate(raw)
    except ValidationError:
        return None

    query = update.callback_query
    if query is not None:
        if query.data is None or query.message is None or len(query.id) > _MAX_CALLBACK_QUERY_ID:
            return None
        return ButtonPress(
            update_id=update.update_id,
            callback_query_id=query.id,
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            data=query.data,
        )

    message = update.message
    if message is None:
        return None
    if message.voice is not None:
        voice = message.voice
        return IncomingVoice(
            update_id=update.update_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            file_id=voice.file_id,
            duration=voice.duration,
            mime_type=voice.mime_type,
            file_size=voice.file_size,
        )
    if message.text is not None:
        # NUL не принимают ни JSONB, ни TEXT Postgres: без удаления такой апдейт падал бы при каждой
        # обработке (S2b). Пустой после очистки текст — пустое сообщение, его не обрабатываем.
        stripped = message.text.replace("\x00", "").strip()
        # Команды не являются задачами: /start и другие «/…» отбрасываются (design.md, решение 14).
        if not stripped or stripped.startswith("/"):
            return None
        return IncomingText(
            update_id=update.update_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=stripped,
        )
    return None


def dump_incoming(incoming: Incoming) -> dict[str, Any]:
    """Превращает событие в JSON-совместимый dict для колонки telegram_updates.payload."""
    return incoming.model_dump(mode="json")


def load_incoming(payload: object) -> Incoming | None:
    """Восстанавливает событие из payload. None — если payload пуст или не проходит проверку."""
    if payload is None:
        return None
    try:
        return _INCOMING.validate_python(payload)
    except ValidationError:
        return None


def dedup_key(incoming: Incoming) -> tuple[UpdateKind, str]:
    """Ключ для защиты от повторной доставки: (kind, external_id) строки telegram_updates."""
    if isinstance(incoming, ButtonPress):
        return ("callback", incoming.callback_query_id)
    return ("update", str(incoming.update_id))
